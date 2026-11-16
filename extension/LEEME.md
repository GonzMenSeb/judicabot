# Extensión de judicabot para la relatoría de la Corte Constitucional

## Qué hace

El servidor de judicabot verifica cada cita de la Corte Constitucional contra el texto de la sentencia en la relatoría. Cuando el servidor no puede descargar esa página (la relatoría bloquea su conexión), se la pide a esta extensión, que la descarga desde el navegador donde está instalada y le devuelve el código HTTP y el contenido.

## Qué envía y qué no

- Solo descarga páginas públicas bajo `https://www.corteconstitucional.gov.co/relatoria/` y rechaza cualquier otra dirección que le pida el servidor.
- Al servidor de judicabot solo le devuelve esas páginas públicas. Nunca recibe ni envía datos del expediente (Acuerdo PCSJA24-12243, art. 8.6).
- La contraseña de judicabot no se guarda: se usa una vez para conectar y el servidor la cambia por una ficha. Si la contraseña cambia en el servidor, la ficha deja de servir y la extensión la vuelve a pedir.

## Instalación en modo de desarrollador

Chrome o Edge, versión 120 o más.

1. Abrir `chrome://extensions` en Chrome o `edge://extensions` en Edge.
2. Activar "Modo de desarrollador".
3. Pulsar "Cargar descomprimida" y elegir la carpeta `judicabot-relatoria` (descargada desde **Inteligencia artificial** en judicabot) o esta carpeta (`extension/`).
4. Abrir la ventana de la extensión desde su ícono en la barra del navegador.
5. Revisar el servidor (por defecto `https://judicabot.web.vespiridion.org`), escribir la contraseña de judicabot y pulsar "Conectar". La ventana debe mostrar "Conectada".

El ícono muestra `!` mientras la extensión no esté conectada.

## Actualización

Reemplazar la carpeta por la versión nueva y pulsar "Volver a cargar" en la tarjeta de la extensión, en `chrome://extensions` o `edge://extensions`.

## Descargarla desde judicabot

judicabot la ofrece ya empaquetada: botón "Descargar extensión (.zip)" en **Inteligencia artificial** (`GET /api/extension/zip`). Quien la reciba descomprime el `.zip` y carga la carpeta `judicabot-relatoria` como se explica arriba.

## Condiciones

- El navegador debe quedar abierto, aunque la pestaña de judicabot esté cerrada: las ejecuciones siguen en el servidor y piden las páginas a la extensión mientras corren. Con el navegador cerrado, las citas que el servidor no pueda verificar quedan para revisar.
- En equipos con políticas que bloquean el modo de desarrollador (por ejemplo, algunos equipos del juzgado) no se puede instalar así.
