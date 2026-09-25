// Cara del compañero de IA
// Placa: ESP32-2424S012  (ESP32-C3 + GC9A01 240x240 redonda + tactil CST816)
//
// La pantalla es la cara. El servidor (tools/buddy_pc.py, en este PC o en una
// maquina Ubuntu) escucha el microfono, piensa la respuesta con un modelo local
// y la dice en voz alta; por el camino que haya va mandando en que estado esta
// y cuanto tiene que abrir la boca.
//
// Ese camino puede ser el cable USB o la red WiFi, y los dos valen a la vez:
// se lee de los dos y se contesta por el que este conectado. Por WiFi manda el
// ESP32 quien abre la conexion (es CLIENTE y el servidor escucha), no al reves.
// Asi la placa puede coger la IP que le de el router, y cuando reinicias el
// servidor es ella la que vuelve a llamar sola, sin tocar nada.
//
// Lo que NO puede hacer esta placa: audio. No lleva microfono, ni altavoz, ni
// codec, y el unico conector que saca pines (P1, SH1.0 de 4) son GND, 3V3, TX y
// RX. Los oidos y la voz viven en el servidor; aqui solo estan la cara y el
// tactil.
//
// La tecnica de los parpados esta tomada de la libreria RoboEyes de FluxGarage:
// los ojos son rectangulos redondeados y las expresiones se consiguen
// RECORTANDOLOS con formas del color del fondo. Un triangulo que baja hacia
// fuera da sueno; hacia dentro, enfado; un rectangulo que sube desde abajo deja
// los ojos sonrientes de toda la vida. Encima de eso, aqui hay degradado,
// reflejos y halo, que en una pantalla de color se puede.
//
// Protocolo, una linea por mensaje:
//   E R|L|P|H    estado: Reposo, escuchando, Pensando, Hablando
//   M N|F|S|T|E  emocion: Neutro, Feliz, Sorpresa, Triste, Enfadado
//   B 0..100     apertura de la boca, mientras habla
//   N 0..100     nivel del microfono: la cara reacciona mientras le hablan
//
// Y en sentido contrario, cuando se toca la cara:
//   C T

#include <Arduino_GFX_Library.h>
#include <Wire.h>
#include <WiFi.h>

#include "secretos.h"

// ---------- pines (los mismos de la placa, verificados) ---------------------
#define LCD_SCLK 6
#define LCD_MOSI 7
#define LCD_CS   10
#define LCD_DC   2
#define LCD_BL   3
#define TP_SDA   4
#define TP_SCL   5
#define TP_INT   0
#define TP_RST   1
#define TP_ADDR  0x15

#define CENTRO 120

// ---------- paleta ----------------------------------------------------------
#define COL_FONDO   0x0041        // #04060A  casi negro, con un punto de azul
#define COL_ALTO    0xBF7F        // #B8EEFF  parte alta del ojo
#define COL_BAJO    0x03B6        // #0076B4  parte baja del ojo
#define COL_BRILLO  0xFFFF        // reflejos
#define COL_HALO    0x0169        // resplandor de alrededor
#define COL_CALIDO_ALTO 0xFF9A    // #FFF2D0  cuando esta contento
#define COL_CALIDO_BAJO 0xFC00    // #FF8000
#define COL_ROJO_ALTO   0xFEDB
#define COL_ROJO_BAJO   0xE000

Arduino_DataBus *bus = new Arduino_ESP32SPI(LCD_DC, LCD_CS, LCD_SCLK, LCD_MOSI, GFX_NOT_DEFINED);
Arduino_GFX *pantalla = new Arduino_GC9A01(bus, GFX_NOT_DEFINED, 0, true);

// La cara entera se compone en RAM y se vuelca de una vez: son 115 KB de los
// ~240 KB libres. Dibujar directo sobre el panel daria parpadeo en cada gesto.
Arduino_Canvas *lienzo = new Arduino_Canvas(240, 240, pantalla, 0, 0);

// ---------- geometria -------------------------------------------------------
#define OJO_IZQ_X   74
#define OJO_DER_X   166
#define OJO_Y      100
#define OJO_ANCHO   60
#define OJO_ALTO    74
#define OJO_RADIO   22
#define BOCA_Y     176

// ---------- estado ----------------------------------------------------------
enum Estado  { REPOSO, ESCUCHANDO, PENSANDO, HABLANDO };
enum Emocion { NEUTRO, FELIZ, SORPRESA, TRISTE, ENFADADO };

Estado  estado  = REPOSO;
Emocion emocion = NEUTRO;
int aperturaPedida = 0;
int nivelMicro = 0;               // lo alto que esta hablando quien tiene delante
uint32_t ultimoNivelAlto = 0;     // cuando se le hablo por ultima vez

// Todo lo que se dibuja son estos numeros. Cada fotograma se acercan un poco a
// su objetivo en vez de saltar: de ahi sale la sensacion de que esta vivo.
struct Rasgos {
  float alto = OJO_ALTO, ancho = OJO_ANCHO;
  float mirarX = 0, mirarY = 0;      // hacia donde mira, en pixeles
  float parpadoSueno = 0;            // triangulo que baja por fuera
  float parpadoEnfado = 0;           // triangulo que baja por dentro
  float parpadoAlegre = 0;           // recorte que sube desde abajo
  float boca = 10;
  float halo = 0.35f;                // intensidad del resplandor
  float inclina = 0;                 // ladea la cara entera
};
Rasgos actual, objetivo;

uint32_t ultimoDato = 0;
bool hayPC() { return ultimoDato && millis() - ultimoDato < 8000; }

// Se considera que le estan hablando hasta medio segundo despues del
// ultimo pico: sin ese margen la cara vibraria con cada pausa entre
// palabras en vez de mantener la atencion.
bool leHablan() { return millis() - ultimoNivelAlto < 500; }

// ============================ TACTIL =======================================
void tactilInit() {
  pinMode(TP_INT, OUTPUT);
  digitalWrite(TP_INT, HIGH); delay(1);
  digitalWrite(TP_INT, LOW);  delay(1);
  pinMode(TP_RST, OUTPUT);
  digitalWrite(TP_RST, LOW);  delay(10);
  digitalWrite(TP_RST, HIGH); delay(300);
  pinMode(TP_INT, INPUT);
  Wire.begin(TP_SDA, TP_SCL, 400000);
  Wire.beginTransmission(TP_ADDR);      // sin esto el chip se duerme solo
  Wire.write(0xFE);
  Wire.write(0xFF);
  Wire.endTransmission();
}

bool tocando() {
  Wire.beginTransmission(TP_ADDR);
  Wire.write(0x02);
  if (Wire.endTransmission(false) != 0) return false;
  Wire.requestFrom((uint8_t)TP_ADDR, (uint8_t)1);
  return Wire.available() && Wire.read() > 0;
}

// ============================ PROTOCOLO ====================================
void procesar(const String &l) {
  if (l.length() < 3) return;
  char c = l.charAt(2);
  switch (l.charAt(0)) {
    case 'E':
      estado = c == 'L' ? ESCUCHANDO : c == 'P' ? PENSANDO
             : c == 'H' ? HABLANDO   : REPOSO;
      break;
    case 'M':
      emocion = c == 'F' ? FELIZ : c == 'S' ? SORPRESA : c == 'T' ? TRISTE
              : c == 'E' ? ENFADADO : NEUTRO;
      break;
    case 'B':
      aperturaPedida = constrain(l.substring(2).toInt(), 0, 100);
      break;
    case 'N':
      nivelMicro = constrain(l.substring(2).toInt(), 0, 100);
      if (nivelMicro > 35) ultimoNivelAlto = millis();
      break;
    default:
      return;
  }
  ultimoDato = millis();
}

// ============================ TRANSPORTE ===================================
// Dos caminos hacia el servidor, cable y WiFi, atendidos igual. El protocolo es
// el mismo por los dos: una linea de texto por mensaje.

WiFiClient clienteRed;
bool radioEncendida = false;

// Cuando no hay nadie al otro lado se reintenta cada 3 s, no a lo loco. El
// intento de conexion TCP es lo unico que bloquea en todo el bucle, asi que se
// le pone un plazo corto: 400 ms perdidos cada 3 s solo pasan mientras esta
// desconectada, y ahi la cara ya esta durmiendo con una animacion lenta donde
// no se nota. Sin ese plazo, el intento por defecto se come varios segundos y
// la cara se queda congelada de verdad.
#define REINTENTO_MS   3000
#define PLAZO_TCP_MS    400

// Manda una linea por donde haya alguien escuchando. El cable siempre, porque
// tambien sirve de consola mientras desarrollas.
void enviar(const char *linea) {
  Serial.println(linea);
  if (clienteRed.connected()) {
    clienteRed.print(linea);
    clienteRed.print('\n');
  }
}

// Saca los caracteres de un flujo cualquiera y va montando lineas. El buffer es
// de cada llamada (uno por camino), porque si no un mensaje a medias por cable
// se mezclaria con otro a medias por red.
void digerir(Stream &flujo, String &buf) {
  while (flujo.available()) {
    char c = flujo.read();
    if (c == '\n') {
      buf.trim();
      procesar(buf);
      buf = "";
    } else if (c != '\r' && buf.length() < 64) {
      buf += c;
    }
  }
}

void leerPC() {
  static String porCable, porRed;
  digerir(Serial, porCable);
  if (clienteRed.connected()) digerir(clienteRed, porRed);
}

void redArrancar() {
  if (strlen(WIFI_SSID) == 0) {
    Serial.println("[red] sin SSID configurado; solo cable");
    return;
  }
  // La radio se enciende DESPUES de que la pantalla ya este dibujando. Este
  // modulo da un tiron de corriente al arrancar el transmisor y, si coincide
  // con el encendido del panel, la placa se reinicia entera (reset por
  // POWERON, no por panico ni por watchdog: costo un buen rato averiguarlo).
  // Bajar la potencia a 11 dBm lo quita del todo y el alcance sigue sobrando
  // para una casa.
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);              // dormir la radio metia medio segundo de retraso
  WiFi.setTxPower(WIFI_POWER_11dBm);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  radioEncendida = true;
  Serial.printf("[red] buscando '%s'...\n", WIFI_SSID);
  // Este numero es el que hay que mirar si la cara se reinicia al conectar. El
  // lienzo de 240x240 ya se ha comido 115 KB y la pila de WiFi pide unos 45 KB
  // mas; en un C3 sin PSRAM eso va justo. Por debajo de ~40 KB libres, mal
  // asunto.
  Serial.printf("[red] heap libre con la radio encendida=%u\n", ESP.getFreeHeap());
}

// Se llama en cada vuelta del bucle y no bloquea (salvo el plazo corto de
// arriba). Nada de esperar a que conecte: la cara tiene que seguir animandose
// aunque el WiFi no aparezca nunca.
void redAtender() {
  if (!radioEncendida || clienteRed.connected()) return;

  static uint32_t proximoIntento = 0;
  static bool avisadoWifi = false;
  if (millis() < proximoIntento) return;
  proximoIntento = millis() + REINTENTO_MS;

  if (WiFi.status() != WL_CONNECTED) {
    avisadoWifi = false;
    return;
  }
  if (!avisadoWifi) {
    Serial.print("[red] WiFi lista, IP ");
    Serial.println(WiFi.localIP());
    avisadoWifi = true;
  }

  if (clienteRed.connect(SERVIDOR_HOST, SERVIDOR_PUERTO, PLAZO_TCP_MS)) {
    // Sin esto, Nagle junta los mensajitos de la boca antes de mandarlos y la
    // cara habla con medio segundo de retraso sobre el audio. Con 30 mensajes
    // por segundo de 6 bytes, agruparlos es justo lo que no queremos.
    clienteRed.setNoDelay(true);
    Serial.printf("[red] conectada a %s:%d\n", SERVIDOR_HOST, SERVIDOR_PUERTO);
  }
}

// ============================ COLOR ========================================
// Interpolacion en RGB565: se separan los tres canales, se mezclan y se vuelven
// a juntar. Hacerlo sobre el entero directamente mezclaria los canales entre si.
uint16_t mezclar(uint16_t a, uint16_t b, float t) {
  t = constrain(t, 0.0f, 1.0f);
  int ra = (a >> 11) & 0x1F, ga = (a >> 5) & 0x3F, ba = a & 0x1F;
  int rb = (b >> 11) & 0x1F, gb = (b >> 5) & 0x3F, bb = b & 0x1F;
  int r = ra + (rb - ra) * t, g = ga + (gb - ga) * t, bl = ba + (bb - ba) * t;
  return (r << 11) | (g << 5) | bl;
}

void coloresOjo(uint16_t &arriba, uint16_t &abajo) {
  switch (emocion) {
    case FELIZ:    arriba = COL_CALIDO_ALTO; abajo = COL_CALIDO_BAJO; break;
    case ENFADADO: arriba = COL_ROJO_ALTO;   abajo = COL_ROJO_BAJO;   break;
    default:       arriba = COL_ALTO;        abajo = COL_BAJO;        break;
  }
}

// ============================ DIBUJO =======================================
// Cuanto se mete el borde hacia dentro en la fila y, para que un rectangulo
// tenga las esquinas redondeadas. Se calcula por filas porque el degradado va
// pintando linea a linea.
int sangrado(int y, int alto, int radio) {
  if (radio <= 0) return 0;
  int d = -1;
  if (y < radio) d = radio - 1 - y;
  else if (y > alto - radio) d = y - (alto - radio);
  if (d < 0) return 0;
  int dentro = radio * radio - d * d;
  return radio - (dentro > 0 ? (int)sqrtf((float)dentro) : 0);
}

void rectDegradado(int x, int y, int w, int h, int radio,
                   uint16_t arriba, uint16_t abajo) {
  if (w <= 0 || h <= 0) return;
  radio = min(radio, min(w, h) / 2);
  for (int fila = 0; fila < h; fila++) {
    int s = sangrado(fila, h, radio);
    int ancho = w - 2 * s;
    if (ancho <= 0) continue;
    lienzo->drawFastHLine(x + s, y + fila, ancho,
                          mezclar(arriba, abajo, (float)fila / (h - 1)));
  }
}

// Resplandor: unos cuantos rectangulos redondeados por fuera, cada vez mas
// tenues. Sale mas barato que un desenfoque de verdad y en una pantalla
// pequena se lee igual.
void halo(int cx, int cy, int w, int h, int radio, float fuerza) {
  if (fuerza < 0.03f) return;
  for (int i = 4; i >= 1; i--) {
    uint16_t c = mezclar(COL_FONDO, COL_HALO, fuerza * (1.0f - i * 0.18f));
    lienzo->drawRoundRect(cx - w / 2 - i * 2, cy - h / 2 - i * 2,
                          w + i * 4, h + i * 4, radio + i * 2, c);
  }
}

// Los dos reflejos son la firma del ojo de anime: uno grande arriba a la
// izquierda y otro pequeno abajo a la derecha.
void reflejos(int cx, int cy, int w, int h) {
  if (h < 20) return;
  lienzo->fillCircle(cx - w / 5, cy - h / 4, max(3, w / 7), COL_BRILLO);
  lienzo->fillCircle(cx + w / 5, cy + h / 5, max(2, w / 14), COL_BRILLO);
}

// izquierdo: -1 el de la izquierda, +1 el de la derecha. Sirve para que los
// parpados de sueno y enfado sean simetricos respecto al centro de la cara.
void parpados(int cx, int cy, int w, int h, int lado) {
  int x = cx - w / 2, y = cy - h / 2;

  if (actual.parpadoSueno > 1) {
    int a = (int)actual.parpadoSueno;
    // la punta baja por el lado de FUERA: parpados caidos
    if (lado < 0) lienzo->fillTriangle(x, y - 1, x + w, y - 1, x, y + a, COL_FONDO);
    else          lienzo->fillTriangle(x, y - 1, x + w, y - 1, x + w, y + a, COL_FONDO);
  }
  if (actual.parpadoEnfado > 1) {
    int a = (int)actual.parpadoEnfado;
    // la punta baja por el lado de DENTRO: ceno fruncido
    if (lado < 0) lienzo->fillTriangle(x, y - 1, x + w, y - 1, x + w, y + a, COL_FONDO);
    else          lienzo->fillTriangle(x, y - 1, x + w, y - 1, x, y + a, COL_FONDO);
  }
  if (actual.parpadoAlegre > 1) {
    // recorte que sube desde abajo: deja el arco de los ojos sonrientes
    lienzo->fillRoundRect(x - 2, y + h - (int)actual.parpadoAlegre,
                          w + 4, h, OJO_RADIO, COL_FONDO);
  }
}

void dibujarOjo(int cx, int lado) {
  int w = max(6, (int)actual.ancho);
  int h = max(3, (int)actual.alto);
  // efecto de curiosidad: el ojo del lado al que mira crece un poco
  float curiosidad = 1.0f + lado * actual.mirarX * 0.004f;
  h = (int)(h * curiosidad);
  w = (int)(w * (1.0f + (curiosidad - 1.0f) * 0.4f));

  int cy = OJO_Y + (int)actual.mirarY + (int)(lado * actual.inclina);
  cx += (int)actual.mirarX;
  int radio = min(OJO_RADIO, min(w, h) / 2);

  uint16_t arriba, abajo;
  coloresOjo(arriba, abajo);

  halo(cx, cy, w, h, radio, actual.halo);
  rectDegradado(cx - w / 2, cy - h / 2, w, h, radio, arriba, abajo);
  reflejos(cx, cy, w, h);
  parpados(cx, cy, w, h, lado);
}

void dibujarBoca() {
  int h = max(4, (int)actual.boca);
  int w = 40 + h;
  uint16_t arriba, abajo;
  coloresOjo(arriba, abajo);
  int y = BOCA_Y + (int)(actual.mirarY * 0.4f);
  halo(CENTRO + (int)(actual.mirarX * 0.3f), y, w, h, h / 2, actual.halo * 0.7f);
  rectDegradado(CENTRO + (int)(actual.mirarX * 0.3f) - w / 2, y - h / 2,
                w, h, h / 2, arriba, abajo);
}

// Lineas de barrido, muy suaves. Le dan aire de holograma sin que se note como
// un efecto pegado encima.
void barrido() {
  uint16_t *fb = lienzo->getFramebuffer();
  for (int y = 1; y < 240; y += 3) {
    uint16_t *fila = fb + y * 240;
    for (int x = 0; x < 240; x++) {
      uint16_t c = fila[x];
      fila[x] = ((c >> 1) & 0x7BEF) + ((c >> 2) & 0x39E7);   // al 75 %
    }
  }
}

void puntosPensando() {
  for (int i = 0; i < 3; i++) {
    float f = sinf(millis() / 240.0f - i * 0.9f);
    int y = 214 + (int)(f * 5);
    uint16_t arriba, abajo;
    coloresOjo(arriba, abajo);
    lienzo->fillCircle(CENTRO - 22 + i * 22, y, 4,
                       f > 0 ? arriba : mezclar(COL_FONDO, abajo, 0.5f));
  }
}

void dibujarCara() {
  lienzo->fillScreen(COL_FONDO);
  dibujarOjo(OJO_IZQ_X, -1);
  dibujarOjo(OJO_DER_X, +1);
  if (actual.boca > 5) dibujarBoca();
  if (estado == PENSANDO) puntosPensando();
  barrido();
  lienzo->flush();
}

// ============================ ANIMACION ====================================
void suavizar(float &v, float destino, float paso) { v += (destino - v) * paso; }

// Muelle con algo de inercia: en vez de frenar justo en el destino, lo pasa un
// poco y vuelve. Es lo que distingue un gesto vivo de una interpolacion.
void rebotar(float &v, float &velocidad, float destino, float tension, float roce) {
  velocidad += (destino - v) * tension;
  velocidad *= roce;
  v += velocidad;
}

// Mirada: se elige un punto al azar cada pocos segundos y ademas se le suma un
// temblor minimo. El ojo humano nunca esta quieto del todo, y sin ese temblor
// la cara parece un dibujo pegado.
void mirada() {
  static uint32_t proximo = 0;
  static float destinoX = 0, destinoY = 0;
  if (millis() > proximo) {
    proximo = millis() + random(1400, 4200);
    destinoX = random(-16, 17);
    destinoY = random(-8, 9);
    if (estado == PENSANDO) { destinoX = random(6, 18); destinoY = -12; }
    if (estado == ESCUCHANDO) { destinoX *= 0.4f; destinoY *= 0.4f; }
  }
  objetivo.mirarX = destinoX + sinf(millis() / 130.0f) * 0.9f;
  objetivo.mirarY = destinoY + cosf(millis() / 170.0f) * 0.6f;
}

void fijarObjetivos() {
  objetivo = Rasgos();
  mirada();

  switch (emocion) {
    case FELIZ:    objetivo.parpadoAlegre = OJO_ALTO * 0.42f; objetivo.halo = 0.7f; break;
    case SORPRESA: objetivo.alto = OJO_ALTO * 1.2f; objetivo.ancho = OJO_ANCHO * 1.12f;
                   objetivo.halo = 0.8f; break;
    case TRISTE:   objetivo.parpadoSueno = OJO_ALTO * 0.42f; objetivo.halo = 0.2f;
                   objetivo.mirarY += 6; break;
    case ENFADADO: objetivo.parpadoEnfado = OJO_ALTO * 0.42f; objetivo.halo = 0.55f; break;
    default: break;
  }

  switch (estado) {
    case ESCUCHANDO: {
      // Mientras nadie habla, respira despacio. En cuanto suena una voz, los
      // ojos se abren y el resplandor sigue al volumen: es lo que convierte
      // "esperando" en "escuchandote".
      float voz = nivelMicro / 100.0f;
      if (leHablan()) {
        objetivo.alto = max(objetivo.alto, OJO_ALTO * (1.12f + voz * 0.22f));
        objetivo.ancho = OJO_ANCHO * (1.0f + voz * 0.08f);
        objetivo.halo = 0.5f + voz * 0.5f;
        objetivo.inclina = -2;                  // se inclina hacia quien habla
      } else {
        objetivo.alto = max(objetivo.alto, OJO_ALTO * 1.06f);
        objetivo.halo = 0.35f + 0.15f * sinf(millis() / 900.0f);
      }
      objetivo.boca = 8;
      break;
    }
    case PENSANDO:
      objetivo.alto *= 0.62f;
      objetivo.parpadoSueno = max(objetivo.parpadoSueno, OJO_ALTO * 0.18f);
      objetivo.halo = 0.3f;
      objetivo.inclina = 4;                       // ladea la cara: gesto de duda
      objetivo.boca = 6;
      break;
    case HABLANDO:
      objetivo.boca = 10 + aperturaPedida * 0.34f;
      // el resplandor sigue a la voz: la cara entera respira con lo que dice
      objetivo.halo = 0.35f + aperturaPedida * 0.005f;
      break;
    case REPOSO:
      objetivo.mirarY += sinf(millis() / 2100.0f) * 2.0f;   // respiracion
      objetivo.alto = OJO_ALTO * 0.94f;
      objetivo.halo = 0.28f + 0.08f * sinf(millis() / 1500.0f);
      objetivo.boca = 8;
      break;
  }

  // Parpadeo. Se cierra rapido y se abre un poco mas despacio, como el de
  // verdad; con la misma velocidad en los dos sentidos parece mecanico.
  static uint32_t proximo = 2500, finParpadeo = 0;
  if (millis() > proximo) {
    finParpadeo = millis() + 120;
    proximo = millis() + random(2400, 6000);
  }
  if (millis() < finParpadeo) objetivo.alto = 3;

  // Sin PC al otro lado se duerme, pero respirando: unos ojos completamente
  // quietos parecen una pantalla colgada, no un companero dormido.
  if (!hayPC()) {
    objetivo.alto = 6 + sinf(millis() / 1600.0f) * 2.0f;
    objetivo.halo = 0.08f + 0.05f * sinf(millis() / 1600.0f);
    objetivo.boca = 0;
    objetivo.parpadoSueno = 4;
    objetivo.mirarX = objetivo.mirarY = 0;
  }
}

void animar() {
  fijarObjetivos();

  // El parpado cierra de golpe y abre con rebote, como el de verdad. Con la
  // misma velocidad en los dos sentidos el parpadeo parece de robot barato.
  static float velAlto = 0;
  bool cerrando = objetivo.alto < actual.alto;
  if (cerrando) {
    velAlto = 0;
    suavizar(actual.alto, objetivo.alto, 0.6f);
  } else {
    rebotar(actual.alto, velAlto, objetivo.alto, 0.28f, 0.72f);
  }
  suavizar(actual.ancho, objetivo.ancho, 0.25f);
  // La mirada salta rapido y frena: los ojos no se desplazan despacio, van a
  // tirones. Copiar ese movimiento es lo que mas ayuda a que parezca mirar.
  suavizar(actual.mirarX, objetivo.mirarX, 0.30f);
  suavizar(actual.mirarY, objetivo.mirarY, 0.30f);
  suavizar(actual.parpadoSueno,  objetivo.parpadoSueno,  0.20f);
  suavizar(actual.parpadoEnfado, objetivo.parpadoEnfado, 0.20f);
  suavizar(actual.parpadoAlegre, objetivo.parpadoAlegre, 0.22f);
  suavizar(actual.boca,  objetivo.boca,  0.5f);     // la boca sigue al audio
  suavizar(actual.halo,  objetivo.halo,  0.30f);   // el brillo sigue a la voz
  suavizar(actual.inclina, objetivo.inclina, 0.1f);
}

// ============================ ARRANQUE =====================================
void introArranque() {
  for (int i = 0; i <= 26; i++) {
    actual.alto = 3 + i * (OJO_ALTO - 3) / 26.0f;
    actual.halo = i / 26.0f;
    actual.boca = 0;
    dibujarCara();
    ledcWrite(LCD_BL, i * 255 / 26);
  }
}

void setup() {
  Serial.setRxBufferSize(2048);
  Serial.begin(115200);
  delay(600);
  Serial.println("\n=== Cara del companero ===");

  pinMode(LCD_BL, OUTPUT);
  ledcAttach(LCD_BL, 5000, 8);
  ledcWrite(LCD_BL, 0);

  pantalla->begin(40000000);
  pantalla->fillScreen(COL_FONDO);
  lienzo->begin();
  tactilInit();
  randomSeed(esp_random());

  Serial.printf("[arranque] heap libre=%u\n", ESP.getFreeHeap());
  introArranque();
  redArrancar();          // la radio, la ultima: ver el comentario de redArrancar
}

void loop() {
  static uint32_t proximoCuadro = 0;
  static bool tocado = false;

  redAtender();
  leerPC();

  bool t = tocando();
  if (t && !tocado) enviar("C T");
  tocado = t;

  if (millis() >= proximoCuadro) {
    proximoCuadro = millis() + 33;        // 30 cuadros por segundo
    animar();
    dibujarCara();
  }
}
