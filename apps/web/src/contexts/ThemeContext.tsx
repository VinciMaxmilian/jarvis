import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';

/**
 * O par de temas é `industry-light` ⇄ `command-dark` (ver PLANOS.md, A.2).
 *
 * O tipo público continua sendo 'light' | 'dark' de propósito: `RulesPage`
 * e `NeuralMap/Engine.ts` já falam essa língua, e trocar o vocabulário aqui
 * quebraria os dois sem ganho nenhum. O nome do design system mora no
 * atributo que vai para o DOM, não no estado.
 */
export type Theme = 'light' | 'dark';

/** O que o CSS enxerga. `industry-light` é o padrão implícito de :root. */
const DOM_THEME: Record<Theme, string> = {
  light: 'industry-light',
  dark: 'command',
};

const STORAGE_KEY = 'jarvis-theme';

interface ThemeContextType {
  theme: Theme;
  setTheme: (theme: Theme) => void;
  toggleTheme: () => void;
}

const ThemeContext = createContext<ThemeContextType | undefined>(undefined);

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(() => {
    // Escolha explícita do usuário vence sempre — inclusive quem trocou
    // para o Industry claro e quer continuar nele.
    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved === 'light' || saved === 'dark') return saved;
    // Sem preferência gravada, o padrão é `command-dark`: é o visual alvo
    // do Jarvis e é o que o desk já força na janela (`theme: "Dark"` no
    // Tauri). Consultar `prefers-color-scheme` aqui só daria claro em
    // máquina de tema claro, contra o desenho do produto.
    return 'dark';
  });

  useEffect(() => {
    const root = document.documentElement;
    // `data-theme` é o contrato do design system. A classe `.dark` segue
    // aplicada porque o CSS legado e a ponte de tokens ainda a listam nos
    // seletores — sai quando a migração por página terminar.
    root.setAttribute('data-theme', DOM_THEME[theme]);
    root.classList.toggle('dark', theme === 'dark');
    localStorage.setItem(STORAGE_KEY, theme);
  }, [theme]);

  const toggleTheme = () => setThemeState(prev => prev === 'light' ? 'dark' : 'light');

  return (
    <ThemeContext.Provider value={{ theme, setTheme: setThemeState, toggleTheme }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  const context = useContext(ThemeContext);
  if (!context) throw new Error('useTheme must be used within a ThemeProvider');
  return context;
}
