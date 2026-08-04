import { clsx } from 'clsx';

/** Cor do valor. `alert` usa o segundo acento — o DS nao tem cor de perigo. */
export type ReadoutTone = 'default' | 'accent' | 'alert';

export interface ReadoutProps {
  /** Rotulo curto, sempre em caixa alta pelo `.card-kicker` (CARGA, UPTIME...). */
  label: string;
  /** Valor ja formatado. Numero cru tambem serve; a formatacao e do chamador. */
  value: string | number;
  /** Unidade colada ao valor (%, ms, MB). Fica menor e em fonte de corpo. */
  unit?: string;
  tone?: ReadoutTone;
  /**
   * Liga o ponto piscante de "dado ao vivo". Respeita prefers-reduced-motion
   * (vira ponto estatico, nao some — a informacao "esta vivo" continua).
   */
  live?: boolean;
  className?: string;
}

/**
 * Leitor de HUD: numero grande monoespacado sobre rotulo pequeno.
 *
 * O valor usa `--ds-font-mono` + `tabular-nums` porque estes numeros mudam a
 * cada poll; com fonte proporcional a largura oscila e o painel inteiro treme.
 */
export function Readout({
  label,
  value,
  unit,
  tone = 'default',
  live = false,
  className,
}: ReadoutProps) {
  const toneClass = tone === 'default' ? undefined : `is-${tone}`;

  return (
    <div className={clsx('ds-readout', className)}>
      <div className="ds-readout-head">
        <span className="card-kicker">{label}</span>
        {live ? <span className={clsx('ds-live', toneClass)} aria-hidden="true" /> : null}
      </div>
      <span className={clsx('ds-readout-value', toneClass)}>
        {value}
        {unit ? <span className="ds-readout-unit text-muted">{unit}</span> : null}
      </span>
    </div>
  );
}
