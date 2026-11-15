# Requisitos: extensión de navegador para leer la relatoría desde Colombia

Fecha: 2026-11-15. Insumo para planear e implementar. Dice qué se necesita y por qué; el cómo queda a quien implemente.

## Por qué

- Judicabot verifica cada cita de la Corte Constitucional contra el texto de la sentencia en la relatoría (`https://www.corteconstitucional.gov.co/relatoria/AAAA/T-NNN-AA.htm`).
- En producción el backend corre en un VPS de OVH en Singapur (`judicabot.web.vespiridion.org`). La relatoría está detrás de un WAF de Azure que le responde 403 a ese servidor. Desde una conexión residencial colombiana responde bien.
- Desde el PR #2 (merge `c359046`, 2026-11-15), una página inaccesible deja la cita "para revisar" y el `.docx` la marca con `⟦FALTA: cita sin verificar…⟧`. En producción, entonces, ninguna cita se verifica contra el texto y el usuario tiene que revisarlas todas a mano.
- La página web de judicabot no puede descargarlas por el usuario: las `.htm` de la relatoría no envían `Access-Control-Allow-Origin`, así que el navegador no deja leer la respuesta (comprobado en Chromium y con `curl`). El buscador (`/relatoria/buscador_new/`) sí envía `Access-Control-Allow-Origin: *`, pero solo devuelve metadatos, no el texto.
- Una extensión con permiso sobre el dominio de la relatoría sí puede leer esas páginas. Instalada en el navegador del usuario, que está en Colombia, descarga desde su conexión.
- Alternativas descartadas: programa de Windows (.exe), proxy en otra máquina, corpus sincronizado por lotes.

## Lo que hay hoy en `main`

- `backend/tutela2/citas.py`:
  - `_bajar_pagina(url)` es el único punto que descarga páginas de la relatoría (urllib, timeout 60 s).
  - `consultar_relatoria(url, cfg)` busca primero en la caché en disco (`<cache>/relatoria/<archivo>.htm`). Si no está, descarga, clasifica con `_clasificar_pagina` (`ok`, `no_publicada`, `inaccesible`) y guarda en caché solo si `_es_pagina_de` confirma que es la sentencia pedida.
  - `verificar_citas` la llama una vez por URL, en secuencia, y emite eventos de progreso, entre ellos el aviso de citas sin acceso.
- En producción la caché está en `/opt/judicabot/casos/.cache/relatoria` del VPS (`TUTELA2_CACHE_DIR=/data/casos/.cache` en el contenedor).
- Las ejecuciones (`POST /api/casos/{caso_id}/run`, `backend/tutela2/server.py`) corren en un hilo del servidor y siguen aunque el usuario cierre la pestaña.
- `backend/tutela2/acceso.py` protege todo con una contraseña única (`JUDICABOT_PASSWORD`) y la cookie `judicabot_acceso` (HttpOnly, SameSite=Lax). Solo `/healthz` queda exento.
- La CSP de la página está en `backend/tutela2/estaticos.py`.
- Sobre las páginas: las reales empiezan con un script `encabezado.js` y vienen en windows-1252 o utf-8. Una sentencia aún no publicada responde 200 con un shell de Angular de unos 8,6 KB. La más grande vista, C-313/14, pesa 4,6 MB y tardó 19,5 s.

## Requisitos

1. Extensión para Chrome y Edge, publicada como no listada en la Chrome Web Store (Edge instala desde ahí).
2. La extensión solo descarga URLs bajo `https://www.corteconstitucional.gov.co/relatoria/` y rechaza cualquier otra que le pida el servidor.
3. Funciona mientras el navegador esté abierto, aunque la pestaña de judicabot esté cerrada, porque las ejecuciones siguen en el servidor sin ella. Hay que comprobar cómo mantener vivo el service worker de Manifest V3 mientras espera pedidos.
4. El servidor pide la URL y la extensión devuelve el código HTTP y los bytes crudos. La clasificación, la validación de que es la sentencia pedida y la caché siguen en el servidor con el código actual. Deben pasar páginas de varios MB.
5. Orden de consulta: caché, descarga directa del servidor, extensión. La descarga directa se queda para que el backend siga funcionando sin extensión cuando corre en Colombia.
6. Si no hay extensión conectada, o no responde a tiempo, la cita queda "para revisar" como hoy y la ejecución no se bloquea. El aviso de citas sin acceso distingue "la extensión no estaba conectada" de "la relatoría rechazó la petición".
7. La conexión entre la extensión y el servidor queda detrás del mismo control de acceso de `acceso.py`: sin la contraseña nadie puede conectarse como extensión ni recibir o entregar páginas.
8. A la extensión solo le llegan URLs de sentencias públicas, nunca datos del expediente (Acuerdo PCSJA24-12243, art. 8.6).

## Fuera de alcance

- Firefox, Safari y aplicaciones de escritorio.
- Otras fuentes (CSJ, Consejo de Estado, Senado): hoy el verificador solo descarga la relatoría de la Corte Constitucional.
- Descargar o sincronizar el corpus completo.

## Criterios de aceptación

- En producción, con la extensión instalada en un navegador con conexión colombiana, `consultar_relatoria` sobre URLs conocidas da:
  - T-200/22 (`https://www.corteconstitucional.gov.co/relatoria/2022/T-200-22.htm`): `ok`, con el texto y la página guardada en la caché del VPS.
  - SU-319/26: `no_publicada`. Al 2026-11-15 está en el dataset de datos.gov.co, pero la relatoría devuelve el shell.
- Con el navegador cerrado, las mismas consultas dan `inaccesible` con el aviso de extensión no conectada, y no bloquean la ejecución.
- Una ejecución del caso sintético (`backend/scripts/caso_sintetico.py`) en producción verifica contra el texto las citas de la Corte Constitucional que proponga el modelo.
- Sin extensión, el backend corriendo en una máquina en Colombia sigue descargando directo.
- Las pruebas existentes siguen pasando y el flujo nuevo tiene las suyas. `test_sdk_real_sin_clave_da_error_claro` ya falla en `main` en la máquina de desarrollo; no es parte de este trabajo.

## Restricciones de trabajo

- Para pruebas contra servicios externos se usa solo el caso sintético, nunca expedientes reales.
- El VPS se revisa con `ssh vps`, solo lectura. Jenkins despliega al fusionar en `main`.

## Pendiente del usuario

- Crear la cuenta de desarrollador de la Chrome Web Store (pago único de US$5) para publicar la extensión.
- Confirmar qué navegador usa el usuario final y si usa judicabot en un PC propio o en uno del juzgado, donde las extensiones pueden estar bloqueadas. Este documento supone Chrome o Edge en un PC propio.
