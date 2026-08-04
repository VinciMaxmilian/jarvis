import { clsx } from 'clsx';
import type { KeyboardEvent, ReactNode } from 'react';

export type DataTableAlign = 'left' | 'right' | 'center';

export interface DataTableColumn<Row> {
  /** Chave estavel da coluna. Serve de `key` do React, nao acessa a linha. */
  key: string;
  header: ReactNode;
  /** Extrai a celula da linha. Recebe o indice para numeracao/ordinal. */
  cell: (row: Row, index: number) => ReactNode;
  align?: DataTableAlign;
  /** Aplica mono + digitos tabulares. Ligue em toda coluna numerica. */
  numeric?: boolean;
  /** Largura da coluna. Use unidade relativa ou `var(--space-*)`, nunca px. */
  width?: string;
}

export interface DataTableProps<Row> {
  columns: readonly DataTableColumn<Row>[];
  rows: readonly Row[];
  /** Identidade da linha. Indice como chave quebra animacao e foco ao reordenar. */
  rowKey: (row: Row, index: number) => string;
  /** `<caption>` da tabela. Some visualmente se o DS assim definir, mas o
   *  leitor de tela sempre le — por isso vale preencher. */
  caption?: string;
  /** Conteudo quando `rows` esta vazio. Padrao: um traco discreto. */
  empty?: ReactNode;
  onRowClick?: (row: Row, index: number) => void;
  className?: string;
}

/**
 * Tabela do DS, generica na linha.
 *
 * Cabecalhos usam `<th scope="col">` — sem `scope` o leitor de tela nao
 * consegue associar celula a coluna em tabela com mais de uma dimensao.
 * Quando ha `onRowClick`, a linha ganha `tabIndex`/`role="button"` e responde
 * a Enter e Espaco: clique-so deixaria a acao inalcancavel pelo teclado.
 */
export function DataTable<Row>({
  columns,
  rows,
  rowKey,
  caption,
  empty = '—',
  onRowClick,
  className,
}: DataTableProps<Row>) {
  const alignClass = (column: DataTableColumn<Row>) =>
    column.align === 'right'
      ? 'ds-align-right'
      : column.align === 'center'
        ? 'ds-align-center'
        : undefined;

  const handleKeyDown = (event: KeyboardEvent<HTMLTableRowElement>, row: Row, index: number) => {
    if (!onRowClick) return;
    if (event.key !== 'Enter' && event.key !== ' ') return;
    // Espaco rolaria a pagina; Enter poderia disparar submit de um form pai.
    event.preventDefault();
    onRowClick(row, index);
  };

  return (
    <div className="ds-table-wrap">
      <table className={clsx('table', className)}>
        {caption ? <caption>{caption}</caption> : null}
        <thead>
          <tr>
            {columns.map((column) => (
              <th
                key={column.key}
                scope="col"
                className={alignClass(column)}
                style={column.width ? { width: column.width } : undefined}
              >
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={columns.length} className="ds-table-empty text-muted">
                {empty}
              </td>
            </tr>
          ) : (
            rows.map((row, index) => (
              <tr
                key={rowKey(row, index)}
                className={clsx(onRowClick && 'ds-row-clickable')}
                onClick={onRowClick ? () => onRowClick(row, index) : undefined}
                onKeyDown={onRowClick ? (event) => handleKeyDown(event, row, index) : undefined}
                tabIndex={onRowClick ? 0 : undefined}
                role={onRowClick ? 'button' : undefined}
              >
                {columns.map((column) => (
                  <td
                    key={column.key}
                    className={clsx(alignClass(column), column.numeric && 'ds-num')}
                  >
                    {column.cell(row, index)}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
