#pragma once
// Copia este archivo como "secretos.h" y rellena los datos. secretos.h NO va al
// repositorio: lleva la contrasena de tu WiFi.

// ---- WiFi -----------------------------------------------------------------
// Deja el SSID vacio ("") para trabajar solo por cable USB: la radio ni se
// enciende y la cara funciona igual que antes.
//
// IMPORTANTE: el ESP32-C3 solo habla 2.4 GHz. No ve ninguna red de 5 GHz. Si tu
// router publica las dos bandas con el mismo nombre suele valer igual, pero si
// no conecta, esa es la primera sospecha.
#define WIFI_SSID  ""
#define WIFI_PASS  ""

// ---- Servidor -------------------------------------------------------------
// Donde corre tools/buddy_pc.py: la IP de tu PC o de la maquina Ubuntu. Tiene
// que ser una IP fija o una reserva por DHCP en el router; si el servidor
// cambia de IP, la cara se queda llamando a la puerta equivocada.
//
// Para saberla:   Windows -> ipconfig     Linux -> ip addr
#define SERVIDOR_HOST   "192.168.1.50"
#define SERVIDOR_PUERTO 8787
