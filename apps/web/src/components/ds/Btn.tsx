import { clsx } from 'clsx';
import type { ComponentPropsWithRef, ReactNode } from 'react';

export type BtnVariant = 'primary' | 'secondary' | 'ghost' | 'icon';

export interface BtnProps extends ComponentPropsWithRef<'button'> {
  /**
   * Padrao `secondary`. `primary` e a unica forma solida do DS — usar mais de
   * uma por painel destroi a hierarquia que o visual inteiro depende.
   */
  variant?: BtnVariant;
  /** Ocupa a largura do contêiner (`.btn-block`). */
  block?: boolean;
  /**
   * Icone como ReactNode — ver a nota de desacoplamento em `Panel`.
   * Com `variant="icon"` e sem `children`, passe tambem `aria-label`: o botao
   * fica sem texto acessivel de outro jeito.
   */
  icon?: ReactNode;
  children?: ReactNode;
}

/**
 * Botao do DS.
 *
 * `type="button"` por padrao de proposito: o default do HTML e `submit`, e um
 * botao de acao dentro de `<form>` acabaria enviando o formulario sem querer.
 */
export function Btn({
  variant = 'secondary',
  block = false,
  icon,
  children,
  className,
  type = 'button',
  ...rest
}: BtnProps) {
  return (
    <button
      type={type}
      className={clsx('btn', `btn-${variant}`, block && 'btn-block', className)}
      {...rest}
    >
      {icon ? (
        <span className="ds-icon" aria-hidden="true">
          {icon}
        </span>
      ) : null}
      {children}
    </button>
  );
}
