import { Boton } from "../../ui";
import "./estilos.css";

export default function Extension() {
  return (
    <div data-vista="extension" class="extension">
      <p class="sub">
        La relatoría de la Corte Constitucional y la página de certificados de vigencia de la Rama Judicial rechazan las consultas de este servidor. La extensión las hace desde un navegador en Colombia: descarga las sentencias citadas para verificar las citas y, cuando la consulta automática está activada en el servidor, el certificado de vigencia de la tarjeta profesional de los abogados del expediente.
      </p>
      <p class="sub extension-alcance">
        Para el certificado solo envía el número de cédula del abogado, y solo a la página de certificados de la Rama Judicial; trae de vuelta el PDF público. Para que la consulta llegue a un solo servidor, el navegador envía a esa página las cookies que tenga de la Rama Judicial; la consulta solo necesita las dos de afinidad que pone la propia página, que no tienen datos personales. No hay inicio de sesión, no sigue redirecciones y no se envía ninguna cookie de otros sitios. La consulta de la relatoría no cambia y sigue sin cookies.
      </p>
      <Boton href="/api/extension/zip" download="">
        Descargar extensión (.zip)
      </Boton>
      <ol class="extension-pasos" aria-label="Pasos para instalar la extensión">
        <li>
          Descomprima el archivo descargado y mueva la carpeta <code>judicabot-relatoria</code> que queda adentro a un lugar fijo, por ejemplo Documentos. No la borre: el navegador la usa mientras la extensión esté instalada.
        </li>
        <li>
          En Chrome abra <code>chrome://extensions</code>; en Edge, <code>edge://extensions</code>.
        </li>
        <li>Active «Modo de desarrollador».</li>
        <li>
          Pulse «Cargar extensión sin empaquetar» (según el navegador puede decir «Cargar descomprimida» o «Cargar desempaquetado») y elija la carpeta <code>judicabot-relatoria</code> (la que contiene <code>manifest.json</code>).
        </li>
        <li>
          Abra la extensión desde el botón de extensiones del navegador. En «Servidor» debe quedar <code>{location.origin}</code>; escriba la contraseña de judicabot y pulse «Conectar». Debe aparecer «Conectada».
        </li>
        <li>Deje ese navegador abierto. Si se cierra, las citas que el servidor no pueda verificar quedan para revisar, y el certificado de vigencia de cada abogado se sube a mano desde el borrador.</li>
      </ol>
      <p class="sub extension-nota">
        Para actualizarla, descargue el archivo de nuevo, descomprímalo y copie el contenido de su carpeta <code>judicabot-relatoria</code> sobre la carpeta que ya instaló, reemplazando los archivos; después pulse el botón de volver a cargar (la flecha circular) en la tarjeta de la extensión y, si el navegador lo pide, acepte el acceso a la página de la Rama Judicial. El certificado de vigencia necesita la versión 1.1.0 o más; con una anterior, la relatoría sigue funcionando. Si su equipo no deja activar el modo de desarrollador, pida ayuda a soporte técnico.
      </p>
    </div>
  );
}
