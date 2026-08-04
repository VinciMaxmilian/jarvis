import { clsx } from 'clsx';
import { useCallback, useEffect, useId, useRef } from 'react';
import { createPortal } from 'react-dom';
import type { MouseEvent, ReactNode } from 'react';

/**
 * Seletor do que e focavel. `[tabindex]:not([tabindex="-1"])` cobre elementos
 * customizados; `:not([disabled])` evita parar o Tab num controle inerte.
 */
const FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',');

export interface DialogProps {
  open: boolean;
  /** Chamado por Esc, clique no backdrop e pelos botoes de acao do chamador. */
  onClose: () => void;
  title: string;
  children: ReactNode;
  /** Botoes do rodape. Costumam ser `<Btn variant="primary">` + secundario. */
  actions?: ReactNode;
  /**
   * Padrao `true`. Desligue em confirmacao destrutiva (Gate 2): ali a saida
   * tem que ser uma escolha explicita, nao um Esc reflexo.
   */
  dismissible?: boolean;
  className?: string;
}

/**
 * Modal do DS.
 *
 * Vai em portal no `<body>` para escapar de qualquer `overflow`/`transform` de
 * painel ancestral, que criaria contexto de empilhamento e cortaria o modal.
 * Enquanto aberto: foco preso dentro, scroll do fundo travado, e o foco
 * anterior restaurado no fechamento.
 */
export function Dialog({
  open,
  onClose,
  title,
  children,
  actions,
  dismissible = true,
  className,
}: DialogProps) {
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const titleId = useId();

  // onClose costuma vir inline do chamador; a ref evita reassinar o listener e
  // refazer o foco a cada render do pai.
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  useEffect(() => {
    if (!open) return;

    const node = dialogRef.current;
    const previouslyFocused = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;

    const getFocusable = (): HTMLElement[] =>
      node ? Array.from(node.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)) : [];

    // Foca o primeiro controle; sem nenhum, foca o proprio dialogo (tabIndex
    // -1) para que o leitor de tela anuncie o titulo e o Tab fique preso.
    const initial = getFocusable()[0] ?? node;
    initial?.focus();

    const handleKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Escape') {
        if (!dismissible) return;
        event.preventDefault();
        event.stopPropagation();
        onCloseRef.current();
        return;
      }

      if (event.key !== 'Tab' || !node) return;

      const items = getFocusable();
      if (items.length === 0) {
        event.preventDefault();
        node.focus();
        return;
      }

      const first = items[0];
      const last = items[items.length - 1];
      const active = document.activeElement;

      if (event.shiftKey && (active === first || active === node)) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && active === last) {
        event.preventDefault();
        first?.focus();
      }
    };

    // Fase de captura: pega o Esc antes de qualquer handler da pagina embaixo.
    document.addEventListener('keydown', handleKeyDown, true);

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    return () => {
      document.removeEventListener('keydown', handleKeyDown, true);
      document.body.style.overflow = previousOverflow;
      previouslyFocused?.focus();
    };
  }, [open, dismissible]);

  const handleBackdropMouseDown = useCallback(
    (event: MouseEvent<HTMLDivElement>) => {
      // mousedown (nao click) e a comparacao com currentTarget evitam fechar
      // quando o usuario comeca a selecionar texto dentro e solta o mouse fora.
      if (!dismissible) return;
      if (event.target !== event.currentTarget) return;
      onCloseRef.current();
    },
    [dismissible],
  );

  if (!open) return null;

  return createPortal(
    <div className="dialog-backdrop ds-dialog-backdrop" onMouseDown={handleBackdropMouseDown}>
      <div
        ref={dialogRef}
        className={clsx('dialog', 'blueprint', 'ds-dialog', className)}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
      >
        <i className="corner tl" aria-hidden="true" />
        <i className="corner tr" aria-hidden="true" />
        <i className="corner bl" aria-hidden="true" />
        <i className="corner br" aria-hidden="true" />

        <h2 className="dialog-title" id={titleId}>
          {title}
        </h2>
        <div className="dialog-body ds-dialog-body">{children}</div>
        {actions ? <div className="dialog-actions">{actions}</div> : null}
      </div>
    </div>,
    document.body,
  );
}
