import { useEffect, useState } from "preact/hooks";

const LINEA = 0.2;

export function useEspia(ids: string[]): string | null {
  const [activa, setActiva] = useState<string | null>(null);
  const clave = ids.join("|");

  useEffect(() => {
    setActiva(ids[0] ?? null);
    if (ids.length === 0 || typeof IntersectionObserver === "undefined") return;
    const elementos = ids.map((id) => document.getElementById(`b-${id}`));

    const calcular = () => {
      const linea = window.innerHeight * LINEA;
      let elegida = 0;
      elementos.forEach((elemento, i) => {
        if (!elemento) return;
        const caja = elemento.getBoundingClientRect();
        const visible = caja.width > 0 || caja.height > 0;
        const pagina = elemento.closest(".bor-pagina");
        const pasada = visible ? caja.top <= linea : pagina !== null && pagina.getBoundingClientRect().bottom <= linea;
        if (pasada) elegida = i;
      });
      const alFinal = window.scrollY > 0 && window.scrollY + window.innerHeight >= document.documentElement.scrollHeight - 2;
      setActiva(ids[alFinal ? ids.length - 1 : elegida] ?? null);
    };

    const observador = new IntersectionObserver(calcular, { rootMargin: "-10% 0px -75% 0px" });
    for (const elemento of elementos) if (elemento) observador.observe(elemento);
    window.addEventListener("scrollend", calcular);
    calcular();
    return () => {
      observador.disconnect();
      window.removeEventListener("scrollend", calcular);
    };
  }, [clave]);

  return activa;
}
