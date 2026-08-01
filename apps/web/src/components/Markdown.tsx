import { lazy, Suspense } from 'react'

const MarkdownRenderer = lazy(() => import('./MarkdownRenderer'))

/**
 * Enquanto o chunk do renderer não chega, mostra o texto cru — o conteúdo
 * nunca some, só ganha formatação um instante depois.
 */
export default function Markdown({ children }: { children: string }) {
  return (
    <div className="markdown-body">
      <Suspense fallback={<span style={{ whiteSpace: 'pre-wrap' }}>{children}</span>}>
        <MarkdownRenderer>{children}</MarkdownRenderer>
      </Suspense>
    </div>
  )
}
