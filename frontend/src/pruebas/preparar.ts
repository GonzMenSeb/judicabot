import { cleanup } from "@testing-library/preact";
import { afterEach } from "vitest";

afterEach(() => {
  cleanup();
  try {
    localStorage.clear();
  } catch {
    // Sin almacenamiento: nada que limpiar.
  }
  // Los filtros viven en la consulta del hash: que no pasen a la siguiente prueba. Se avisa con un hashchange
  // para que el router, si la prueba lo cargó, vacíe `consulta`; no se importa aquí porque cargaría
  // @preact/signals en todas las pruebas y haría más lento cada render.
  history.replaceState(null, "", location.pathname + location.search);
  dispatchEvent(new HashChangeEvent("hashchange"));
});
