import { clsx } from 'clsx';
import type { ReactNode } from 'react';

export interface PanelProps {
  /** Rotulo curto acima do titulo (ex.: "SISTEMA", "BUS"). Vira `.card-kicker`. */
  kicker: string;
  /** Titulo do painel (ex.: "ESTADO DO KERNEL"). Vira `.card-title`. */
  title: string;
  /**
   * Icone opcional ao lado do titulo. Chega como ReactNode de proposito: o
   * primitivo nao importa lucide-react, entao o DS nao fica preso a uma lib
   * de icones nem obriga a instalar dependencia para compilar.
   */
  icon?: ReactNode;
  /** Controles no canto superior direito (botoes, tags de status). */
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  /** Faz o painel ocupar a altura inteira da celula do grid do cockpit. */
  fill?: boolean;
  /** `id` do elemento, util para ancoras e `aria-labelledby` externo. */
  id?: string;
}

/**
 * Moldura padrao de todo painel do cockpit.
 *
 * Emite `.blueprint` + `.card` mais as quatro marcas de registro. As marcas
 * nao sao decoracao opcional: o guia do DS trata um elemento emoldurado sem
 * `.corner` como violacao da gramatica blueprint, e e justamente por isso que
 * elas moram aqui e nao no call site — ninguem consegue esquecer.
 */
export function Panel({
  kicker,
  title,
  icon,
  actions,
  children,
  className,
  fill = false,
  id,
}: PanelProps) {
  return (
    <section
      id={id}
      className={clsx('blueprint', 'card', 'ds-panel', fill && 'ds-panel-fill', className)}
    >
      {/* Puramente visuais -> aria-hidden, para nao poluir o leitor de tela. */}
      <i className="corner tl" aria-hidden="true" />
      <i className="corner tr" aria-hidden="true" />
      <i className="corner bl" aria-hidden="true" />
      <i className="corner br" aria-hidden="true" />

      <header className="ds-panel-head">
        <div className="ds-panel-heading">
          <span className="card-kicker">{kicker}</span>
          <h2 className="card-title ds-panel-title">
            {icon ? (
              <span className="ds-icon" aria-hidden="true">
                {icon}
              </span>
            ) : null}
            {title}
          </h2>
        </div>
        {actions ? <div className="ds-panel-actions">{actions}</div> : null}
      </header>

      <div className="card-body ds-panel-body">{children}</div>
    </section>
  );
}
