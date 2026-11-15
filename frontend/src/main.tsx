import { render } from "preact";
import "./estilos/fuentes.css";
import "./estilos/tokens.css";
import "./estilos/base.css";
import "./estilos/ui.css";
import { sincronizarDataset } from "./estado";
import { precargar, Rutas, Shell } from "./rutas";

const raiz = document.getElementById("app");
if (!raiz) throw new Error("Falta el contenedor #app");

void precargar();
void sincronizarDataset();
render(
  <Shell>
    <Rutas />
  </Shell>,
  raiz,
);
