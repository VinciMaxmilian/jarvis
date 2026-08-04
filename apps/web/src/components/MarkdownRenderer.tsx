import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import rehypeRaw from 'rehype-raw'

// Isolado num módulo próprio para virar um chunk separado: react-markdown +
// katex somam a maior parte do bundle e não são necessários no primeiro paint.
const REMARK = [remarkGfm, remarkMath]
const REHYPE = [rehypeRaw, rehypeKatex]

export default function MarkdownRenderer({ children }: { children: string }) {
  return (
    <ReactMarkdown remarkPlugins={REMARK} rehypePlugins={REHYPE}>
      {children}
    </ReactMarkdown>
  )
}
