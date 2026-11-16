import { Boton } from "../../ui";
import "./estilos.css";

export default function Extension() {
  return (
    <div data-vista="extension" class="extension">
      <p class="sub">La relatoría de la Corte Constitucional rechaza las consultas de este servidor. La extensión las hace desde un navegador en Colombia para verificar las citas.</p>
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
        <li>Deje ese navegador abierto. Si se cierra, las citas que el servidor no pueda verificar quedan para revisar.</li>
      </ol>
      <p class="sub extension-nota">
        Para actualizarla, descargue el archivo de nuevo, descomprímalo y copie el contenido de su carpeta <code>judicabot-relatoria</code> sobre la carpeta que ya instaló, reemplazando los archivos; después pulse el botón de volver a cargar (la flecha circular) en la tarjeta de la extensión. Si su equipo no deja activar el modo de desarrollador, pida ayuda a soporte técnico.
      </p>
    </div>
  );
}
