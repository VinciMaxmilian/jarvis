import { clsx } from 'clsx';
import { useId } from 'react';
import type { ComponentPropsWithRef, ReactNode } from 'react';

/**
 * Props que o `Field` entrega ao controle. Existe para que o campo cuide de
 * `id`, `aria-describedby` e `aria-invalid` sem o chamador ter que repetir
 * essa amarracao (e sem `cloneElement`, que quebra com qualquer wrapper).
 */
export interface FieldControlProps {
  id: string;
  'aria-describedby'?: string;
  'aria-invalid'?: boolean;
}

export interface FieldProps {
  label: string;
  /** Force um id proprio quando o controle ja tiver um. Senao vem de `useId`. */
  htmlFor?: string;
  /** Texto de ajuda abaixo do controle. Suprimido quando ha `error`. */
  hint?: string;
  /** Mensagem de erro. Presente => o controle recebe `aria-invalid`. */
  error?: string;
  /**
   * ReactNode simples, ou funcao que recebe as props de amarracao.
   * A forma de funcao e a preferida: `{(c) => <Input {...c} />}`.
   */
  children: ReactNode | ((control: FieldControlProps) => ReactNode);
  className?: string;
}

/** Rotulo + controle + ajuda/erro, sobre `.field`. */
export function Field({ label, htmlFor, hint, error, children, className }: FieldProps) {
  const generatedId = useId();
  const id = htmlFor ?? generatedId;
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;
  // Erro tem prioridade sobre a dica: anunciar os dois faz o leitor de tela
  // ler a instrucao antes da falha, escondendo o que importa.
  const describedBy = error ? errorId : hint ? hintId : undefined;

  const control: FieldControlProps = {
    id,
    'aria-describedby': describedBy,
    'aria-invalid': error ? true : undefined,
  };

  return (
    <div className={clsx('field', className)}>
      <label htmlFor={id}>{label}</label>
      {typeof children === 'function' ? children(control) : children}
      {error ? (
        <span className="ds-field-error" id={errorId} role="alert">
          {error}
        </span>
      ) : hint ? (
        <span className="ds-field-hint text-muted" id={hintId}>
          {hint}
        </span>
      ) : null}
    </div>
  );
}

export type InputProps = ComponentPropsWithRef<'input'>;

/** Casca fina sobre `.input`. `type="text"` explicito para nao herdar surpresa. */
export function Input({ className, type = 'text', ...rest }: InputProps) {
  return <input type={type} className={clsx('input', className)} {...rest} />;
}
