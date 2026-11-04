export type Metodo = "GET" | "POST" | "PUT" | "DELETE";

export interface PeticionMock {
  metodo: Metodo;
  ruta: string;
  cuerpo: unknown;
}

export type ManejadorMock = (peticion: PeticionMock) => unknown;

export interface RutaMock {
  metodo: Metodo;
  patron: RegExp;
  responder: ManejadorMock;
}

export type ValorMock = string | number | boolean | null | object;

export interface MockRuta {
  metodo: Metodo;
  ruta: string | RegExp;
  respuesta: ValorMock | ManejadorMock;
}

export const rutasMock: RutaMock[] = [];

const escapar = (texto: string) => texto.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

export function normalizarMock({ metodo, ruta, respuesta }: MockRuta): RutaMock {
  const patron = typeof ruta === "string" ? new RegExp(`^${escapar(ruta)}(?:\\?.*)?$`) : new RegExp(ruta.source, ruta.flags.replace(/[gy]/g, ""));
  const responder: ManejadorMock = typeof respuesta === "function" ? (respuesta as ManejadorMock) : () => structuredClone(respuesta);
  return { metodo, patron, responder };
}

export function agregarMocks(mocks: readonly MockRuta[]): void {
  rutasMock.push(...mocks.map(normalizarMock));
}

const modulosVistas = import.meta.glob<{ mocks?: readonly MockRuta[] }>("../vistas/*/mock.ts", { eager: true });
for (const modulo of Object.values(modulosVistas)) agregarMocks(modulo.mocks ?? []);

agregarMocks([
  {
    metodo: "GET",
    ruta: "/api/estado-servidor",
    respuesta: {
      api_key: true,
      jev_key: false,
      modelo: "claude-sonnet-5-5",
      modelos: ["claude-sonnet-5-5", "claude-haiku-5-5", "claude-opus-5-5"],
    },
  },
]);

export function resolverMock(peticion: PeticionMock): Promise<unknown> | null {
  const coincide = rutasMock.find((r) => r.metodo === peticion.metodo && r.patron.test(peticion.ruta));
  return coincide ? Promise.resolve(coincide.responder(peticion)) : null;
}
