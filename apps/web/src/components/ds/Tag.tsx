import { clsx } from 'clsx';
import type { ReactNode } from 'react';

export type TagTone = 'accent' | 'neutral' | 'outline';

export interface TagProps {
  /** Padrao `neutral`: o acento e caro, guardado para o que realmente destaca. */
  tone?: TagTone;
  /** Icone como ReactNode — ver a nota de desacoplamento em `Panel`. */
  icon?: ReactNode;
  children: ReactNode;
  /** Texto de tooltip nativo, util quando a tag e uma sigla (TRUST, ZERO). */
  title?: string;
  className?: string;
}

/** Etiqueta de estado (STATUS, PRIOR., TRUST). Casca fina sobre `.tag`. */
export function Tag({ tone = 'neutral', icon, children, title, className }: TagProps) {
  return (
    <span className={clsx('tag', `tag-${tone}`, className)} title={title}>
      {icon ? (
        <span className="ds-icon" aria-hidden="true">
          {icon}
        </span>
      ) : null}
      {children}
    </span>
  );
}
