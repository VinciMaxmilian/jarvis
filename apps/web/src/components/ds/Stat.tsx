import { clsx } from 'clsx';
import type { ReactNode } from 'react';

/** Cor do valor. `alert` usa o segundo acento — o DS nao tem cor de perigo. */
export type StatTone = 'default' | 'accent' | 'alert';

export interface StatProps {
  /** Rotulo do indicador (KERNEL, MEMORIA, FILA). */
  label: string;
  /** Valor. Aceita ReactNode para caber `<Tag>` ou icone dentro do numero. */
  value: ReactNode;
  /** Unidade opcional, menor e ao lado do valor. */
  unit?: string;
  tone?: StatTone;
  /** Icone como ReactNode — ver a nota de desacoplamento em `Panel`. */
  icon?: ReactNode;
  className?: string;
}

/**
 * Item da MATRIZ DE SUBSISTEMAS: rotulo + valor + unidade.
 *
 * Diferente do `Readout`, aqui o valor herda a tipografia de titulo do DS
 * (`.card-title`) em vez da mono: sao poucos itens, texto curto, e o alinhamento
 * vertical entre celulas importa mais que a largura fixa do digito.
 */
export function Stat({ label, value, unit, tone = 'default', icon, className }: StatProps) {
  const toneClass = tone === 'default' ? undefined : `is-${tone}`;

  return (
    <div className={clsx('ds-stat', className)}>
      <span className="card-kicker">{label}</span>
      <span className={clsx('card-title', 'ds-stat-value', toneClass)}>
        {icon ? (
          <span className="ds-icon" aria-hidden="true">
            {icon}
          </span>
        ) : null}
        {value}
        {unit ? <span className="ds-stat-unit text-muted">{unit}</span> : null}
      </span>
    </div>
  );
}
