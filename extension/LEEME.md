# Extensión de judicabot para consultas públicas

## Qué hace

El servidor de judicabot necesita dos páginas públicas que bloquean su conexión (responden 403 a las IP de fuera de Colombia). Se las pide a esta extensión, que las consulta desde el navegador donde está instalada y le devuelve el código HTTP y el contenido:

- **Relatoría de la Corte Constitucional.** Para verificar cada cita contra el texto de la sentencia.
- **Certificado de vigencia de la tarjeta profesional** (Rama Judicial, desde la versión 1.1.0). Para verificar que los abogados del expediente tienen la tarjeta vigente. Solo se usa si la consulta automática está activada en el servidor (ver más abajo).

## Qué envía y qué no

- Solo hace dos consultas públicas: páginas de sentencias bajo `https://www.corteconstitucional.gov.co/relatoria/` y el certificado de vigencia de la tarjeta profesional en `https://vigenciaspublicas.ramajudicial.gov.co/Certificados.aspx`. Rechaza cualquier otra dirección, método o campo, aunque se lo pida el servidor.
- Para el certificado, el servidor le entrega únicamente el número de cédula del abogado (el que consta en el expediente, o el que corrija a mano quien revisa el borrador), y la extensión lo envía solo a esa página de la Rama Judicial, en un formulario con siete campos fijos: los tres campos ocultos de la propia página, la calidad «abogado», el tipo de documento «cédula de ciudadanía», el número de cédula y el botón «Generar». Devuelve al servidor el PDF público del certificado. No recibe ni envía ningún otro dato del expediente (Acuerdo PCSJA24-12243, art. 8.6). Para que el GET y el POST lleguen al mismo servidor, el navegador envía a esa página las cookies que tenga de la Rama Judicial; la consulta solo necesita las dos de afinidad que pone la propia página, que no tienen datos personales. No hay inicio de sesión y no se envía ninguna cookie de otros sitios. Ni el GET ni el POST siguen redirecciones.
- La relatoría funciona igual que antes: solo se descargan páginas públicas de sentencias, sin ningún dato del expediente y sin cookies.
- La contraseña de judicabot no se guarda: se usa una vez para conectar y el servidor la cambia por una ficha. Si la contraseña cambia en el servidor, la ficha deja de servir y la extensión la vuelve a pedir.

## Consulta automática de vigencia: apagada por defecto

Mientras la URNA y el área jurídica no la aprueben por escrito, el servidor no pide certificados de vigencia: nada se pone en cola ni sale hacia la Rama Judicial, y el borrador ofrece subir a mano el PDF del certificado. Con la aprobación, se enciende en el servidor de una de dos maneras:

- para toda la instalación, con la variable de entorno `TUTELA2_CONSULTA_VIGENCIA=extension` (manda sobre la configuración de cada caso; `apagada`, o cualquier valor que no sea `extension` ni `directa`, la vuelve a apagar);
- para un caso, con `"apoderados": {"consulta": "extension"}` en su `config.json`.

El valor `directa` hace que la consulta la haga el propio servidor, sin la extensión; solo sirve en servidores con conexión colombiana. Pasa por la misma lista de lo permitido que la extensión antes de enviarse y no sigue ninguna redirección; las cookies de afinidad de la página viven solo en memoria durante cada consulta y se descartan al terminar.

## Instalación en modo de desarrollador

Chrome o Edge, versión 120 o más.

1. Descargar el `.zip` desde **Configuración → Extensión de consultas públicas** (engranaje de la barra) en judicabot, descomprimirlo y mover la carpeta `judicabot-relatoria` a un lugar fijo, por ejemplo Documentos. No borrarla: el navegador la usa mientras la extensión esté instalada. (También se puede cargar esta carpeta, `extension/`.)
2. Abrir `chrome://extensions` en Chrome o `edge://extensions` en Edge.
3. Activar "Modo de desarrollador".
4. Pulsar "Cargar extensión sin empaquetar" (según el idioma y el navegador puede decir "Cargar descomprimida" o "Cargar desempaquetado") y elegir esa carpeta `judicabot-relatoria`.
5. Abrir la ventana de la extensión desde su ícono en la barra del navegador.
6. Revisar el servidor (por defecto `https://judicabot.web.vespiridion.org`), escribir la contraseña de judicabot y pulsar "Conectar". La ventana debe mostrar "Conectada".

El ícono muestra `!` mientras la extensión no esté conectada.

## Actualización

Descargar el .zip de nuevo desde **Configuración → Extensión de consultas públicas**, descomprimirlo y copiar el contenido de su carpeta `judicabot-relatoria` sobre la carpeta ya instalada, reemplazando los archivos. Después pulsar el botón de volver a cargar (la flecha circular) en la tarjeta de la extensión, en `chrome://extensions` o `edge://extensions`. Si se carga otra carpeta, el navegador la instala como una extensión distinta, sin la conexión guardada.

El certificado de vigencia necesita la versión 1.1.0 o más. Con la 1.0.0 la relatoría sigue funcionando, pero el servidor nunca le pide certificados: el borrador la muestra como desactualizada y ofrece subir el certificado a mano. Al volver a cargarla, el navegador puede pedir que se acepte el acceso al nuevo sitio (la página de certificados de la Rama Judicial).

## Descargarla desde judicabot

judicabot la ofrece ya empaquetada: botón "Descargar extensión (.zip)" en **Configuración → Extensión de consultas públicas** (`GET /api/extension/zip`). Quien la reciba descomprime el `.zip` y carga la carpeta `judicabot-relatoria` como se explica arriba.

## Condiciones

- El navegador debe quedar abierto, aunque la pestaña de judicabot esté cerrada: las ejecuciones siguen en el servidor y piden las páginas a la extensión mientras corren. Con el navegador cerrado, las citas que el servidor no pueda verificar quedan para revisar, y los certificados de vigencia esperan a que la extensión se reconecte o se suben a mano.
- Las consultas de vigencia salen de a una, con al menos 30 segundos entre una y otra, y el servidor guarda el resultado un día.
- En equipos con políticas que bloquean el modo de desarrollador (por ejemplo, algunos equipos del juzgado) no se puede instalar así.
