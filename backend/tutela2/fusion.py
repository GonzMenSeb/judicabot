from __future__ import annotations

from difflib import SequenceMatcher

Cambio = tuple[int, int, list[str]]


def _cambios(base: list[str], lado: list[str]) -> list[Cambio]:
    cambios: list[Cambio] = []
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, base, lado, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        if tag == "replace" and i2 - i1 == j2 - j1:
            partes = [(i1 + k, i1 + k + 1, lado[j1 + k : j1 + k + 1]) for k in range(i2 - i1)]
        else:
            partes = [(i1, i2, lado[j1:j2])]
        cambios += [c for c in partes if c[2] != base[c[0] : c[1]]]
    return cambios


def _solapan(a: Cambio, b: Cambio) -> bool:
    if a[0] < b[1] and b[0] < a[1]:
        return True
    return a[0] == a[1] == b[0] == b[1]


def _racimos(mios: list[Cambio], nuevos: list[Cambio]) -> list[list[tuple[str, Cambio]]]:
    items = [("mio", c) for c in mios] + [("nuevo", c) for c in nuevos]
    padre = list(range(len(items)))

    def raiz(i: int) -> int:
        while padre[i] != i:
            padre[i] = padre[padre[i]]
            i = padre[i]
        return i

    for i, (lado_a, a) in enumerate(items):
        for j in range(i + 1, len(items)):
            lado_b, b = items[j]
            if lado_a != lado_b and _solapan(a, b):
                padre[raiz(i)] = raiz(j)
    grupos: dict[int, list[tuple[str, Cambio]]] = {}
    for i, item in enumerate(items):
        grupos.setdefault(raiz(i), []).append(item)
    return list(grupos.values())


def _aplicar(base: list[str], lo: int, hi: int, cambios: list[Cambio]) -> list[str]:
    salida: list[str] = []
    pos = lo
    for ini, fin, nuevo in sorted(cambios, key=lambda c: (c[0], c[1])):
        salida += base[pos:ini] + nuevo
        pos = fin
    return salida + base[pos:hi]


def fusionar(base: list[str], mio: list[str], nuevo: list[str]) -> list[dict]:
    racimos = []
    for grupo in _racimos(_cambios(base, mio), _cambios(base, nuevo)):
        lo = min(c[0] for _, c in grupo)
        hi = max(c[1] for _, c in grupo)
        racimos.append((lo, hi, grupo))
    racimos.sort(key=lambda r: (r[0], r[1]))

    trozos: list[dict] = []
    pos = 0
    for lo, hi, grupo in racimos:
        if lo > pos:
            trozos.append({"tipo": "ok", "origen": "igual", "parrafos": base[pos:lo]})
        pos = hi
        zona = base[lo:hi]
        por_lado = {lado: _aplicar(base, lo, hi, [c for l, c in grupo if l == lado]) for lado in {l for l, _ in grupo}}
        if len(por_lado) == 1:
            origen, resultante = next(iter(por_lado.items()))
            trozos.append({"tipo": "ok", "origen": origen, "base": zona, "parrafos": resultante})
        elif por_lado["mio"] == por_lado["nuevo"]:
            trozos.append({"tipo": "ok", "origen": "ambos", "base": zona, "parrafos": por_lado["mio"]})
        else:
            trozos.append({"tipo": "conflicto", "base": zona, "mio": por_lado["mio"], "nuevo": por_lado["nuevo"]})
    if pos < len(base):
        trozos.append({"tipo": "ok", "origen": "igual", "parrafos": base[pos:]})
    return trozos


def hay_conflicto(trozos: list[dict]) -> bool:
    return any(t["tipo"] == "conflicto" for t in trozos)


def resultado(trozos: list[dict], elecciones: list[str] | None = None) -> list[str]:
    elegidas = iter(elecciones or [])
    salida: list[str] = []
    for t in trozos:
        if t["tipo"] == "ok":
            salida += t["parrafos"]
            continue
        lado = next(elegidas, None)
        if lado not in ("mio", "nuevo"):
            raise ValueError("falta la elección de un trozo en conflicto")
        salida += t[lado]
    return salida


def compactar(trozos: list[dict]) -> list[dict]:
    salida: list[dict] = []
    for t in trozos:
        if t["tipo"] == "conflicto":
            salida.append({"tipo": "conflicto", "mio": list(t["mio"]), "nuevo": list(t["nuevo"])})
        elif t["parrafos"]:
            if salida and salida[-1]["tipo"] == "ok":
                salida[-1]["parrafos"] += t["parrafos"]
            else:
                salida.append({"tipo": "ok", "parrafos": list(t["parrafos"])})
    return salida


def escalar(trozos: list[dict]) -> list[dict]:
    return [
        {"tipo": "conflicto", "mio": t["parrafos"], "nuevo": t["base"]}
        if t["tipo"] == "ok" and t.get("origen") == "mio"
        else t
        for t in trozos
    ]
