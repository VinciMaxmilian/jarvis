import { clsx } from 'clsx';
import type { CSSProperties } from 'react';

export interface MeterProps {
  /** Rotulo a esquerda (DISCO, REDE, FILA). Vira tambem o nome acessivel. */
  label?: string;
  value: number;
  /** Padrao 100, para o caso comum de porcentagem. */
  max?: number;
  /** Unidade mostrada ao lado do valor (%, GB, msg). */
  unit?: string;
  /**
   * Fracao de 0..1 a partir da qual a barra entra em alerta. Padrao 0.8 —
   * mesmo limiar que o mock usa para virar a cor de DISCO e FILA.
   */
  threshold?: number;
  /** Esconde o "valor / max" a direita quando o painel ja mostra o numero. */
  showValue?: boolean;
  className?: string;
}

/**
 * Barra de nivel do HUD.
 *
 * `role="progressbar"` em vez de `role="meter"`: leitores de tela ainda tem
 * suporte irregular a `meter`, e progressbar carrega o mesmo trio
 * valuenow/valuemin/valuemax. A largura da barra vai por custom property
 * (`--ds-meter-value`) para o CSS animar `scaleX` sem recalcular layout.
 */
export function Meter({
  label,
  value,
  max = 100,
  unit,
  threshold = 0.8,
  showValue = true,
  className,
}: MeterProps) {
  // Blindagem: max <= 0 viria de dado ruim do backend e produziria NaN/Infinity
  // na largura, quebrando o painel inteiro em vez de so mostrar barra vazia.
  const safeMax = Number.isFinite(max) && max > 0 ? max : 1;
  const safeValue = Number.isFinite(value) ? value : 0;
  const clamped = Math.min(Math.max(safeValue, 0), safeMax);
  const ratio = clamped / safeMax;
  const isAlert = ratio >= threshold;

  const fillStyle = { '--ds-meter-value': `${(ratio * 100).toFixed(2)}%` } as CSSProperties;
  const valueText = unit ? `${clamped} ${unit} de ${safeMax} ${unit}` : `${clamped} de ${safeMax}`;

  return (
    <div className={clsx('ds-meter', isAlert && 'is-alert', className)}>
      {label || showValue ? (
        <div className="ds-meter-head">
          {label ? <span className="card-kicker">{label}</span> : null}
          {showValue ? (
            <span className="ds-meter-value text-muted">
              {clamped}
              {unit ? unit : null}
            </span>
          ) : null}
        </div>
      ) : null}

      <div
        className="ds-meter-track"
        role="progressbar"
        aria-label={label}
        aria-valuenow={clamped}
        aria-valuemin={0}
        aria-valuemax={safeMax}
        aria-valuetext={valueText}
      >
        <span className="ds-meter-fill" style={fillStyle} />
      </div>
    </div>
  );
}
