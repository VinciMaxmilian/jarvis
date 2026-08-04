import { clsx } from 'clsx';
import type { ReactNode } from 'react';

export type FeedTone = 'default' | 'accent' | 'alert' | 'muted';

export interface FeedEvent {
  /** Identidade estavel do evento. Sem ela o React re-anima a lista inteira. */
  id: string;
  /** Timestamp ja formatado. O primitivo nao escolhe locale nem formato. */
  time: string;
  label: ReactNode;
  /** Segunda linha opcional (payload, origem, erro). */
  detail?: ReactNode;
  tone?: FeedTone;
  /** Icone como ReactNode — ver a nota de desacoplamento em `Panel`. */
  icon?: ReactNode;
}

export interface FeedProps {
  /** Ordem de exibicao e a ordem do array — o chamador decide o sentido. */
  events: readonly FeedEvent[];
  /** Corta a lista nos N primeiros. Painel de EVENTOS nao pode crescer sem fim. */
  max?: number;
  empty?: ReactNode;
  /**
   * Anuncia novas linhas em leitor de tela. Desligue em feed de alta
   * frequencia: `aria-live` num fluxo continuo vira ruido e trava a leitura.
   */
  live?: boolean;
  className?: string;
}

/** Lista de eventos (EVENTOS / BUS / FILA) com entrada animada. */
export function Feed({ events, max, empty = 'Sem eventos.', live = true, className }: FeedProps) {
  const visible = typeof max === 'number' ? events.slice(0, max) : events;

  if (visible.length === 0) {
    return <p className="ds-feed-empty text-muted">{empty}</p>;
  }

  return (
    <ul
      className={clsx('ds-feed', className)}
      role={live ? 'log' : undefined}
      aria-live={live ? 'polite' : undefined}
      aria-relevant={live ? 'additions' : undefined}
    >
      {visible.map((event) => {
        const tone = event.tone ?? 'default';
        return (
          <li key={event.id} className={clsx('ds-feed-item', tone !== 'default' && `is-${tone}`)}>
            <time className="ds-feed-time text-muted">{event.time}</time>
            <div className="ds-feed-body">
              <span className="ds-feed-label">
                {event.icon ? (
                  <span className="ds-icon" aria-hidden="true">
                    {event.icon}
                  </span>
                ) : null}
                {event.label}
              </span>
              {event.detail ? (
                <span className="ds-feed-detail text-muted">{event.detail}</span>
              ) : null}
            </div>
          </li>
        );
      })}
    </ul>
  );
}
