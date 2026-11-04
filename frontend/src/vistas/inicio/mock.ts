import type { MockRuta } from "../../api/mock";

export const mocks: MockRuta[] = [
  {
    metodo: "GET",
    ruta: "/api/formato",
    respuesta: {
      campos: [],
      valores: { nombre_cuerpo: "Juzgado Tercero Penal del Circuito con Función de Conocimiento de Medellín" },
      plantilla_gen: "B",
      documentos: [],
    },
  },
];
