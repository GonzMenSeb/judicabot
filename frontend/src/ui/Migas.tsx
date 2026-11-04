export interface ItemMiga {
  texto: string;
  href?: string;
}

export interface PropsMigas {
  items: ItemMiga[];
}

export function Migas({ items }: PropsMigas) {
  const ultimo = items.length - 1;
  return (
    <nav aria-label="Migas de pan">
      <ol class="migas">
        {items.map((item, i) => (
          <li key={`${i}-${item.texto}`}>
            {item.href !== undefined && i < ultimo ? (
              <a href={item.href}>{item.texto}</a>
            ) : (
              <span aria-current={i === ultimo ? "page" : undefined}>{item.texto}</span>
            )}
          </li>
        ))}
      </ol>
    </nav>
  );
}
