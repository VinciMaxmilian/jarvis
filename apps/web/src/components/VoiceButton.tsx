import React, { useEffect, useState, useCallback } from 'react';
import { useDesktopIntegration } from '../hooks/useDesktopIntegration';
import { useVoiceCall } from '../hooks/useVoiceCall';
import { useWakeWord } from '../hooks/useWakeWord';

/**
 * HUD circular no estilo do painel do J.A.R.V.I.S.: anéis concêntricos,
 * marcações radiais e arcos segmentados girando em sentidos opostos.
 *
 * Em SVG e não em imagem: o desenho precisa REAGIR ao estado da chamada — os
 * arcos aceleram quando o agente fala e desaceleram quando ele ouve —, e um
 * PNG só saberia ficar parado. Também sai de graça em qualquer resolução e não
 * soma um byte ao precache do PWA.
 *
 * Uma peça de vidro só (`ritmo`) controla toda a animação: com `prefers-reduced-motion`
 * o navegador congela as rotações via CSS, e o componente continua legível
 * porque a informação está na FORMA, não no movimento.
 */
const JarvisHUD = ({ falando }: { falando: boolean }) => {
  const C = 120; // centro do viewBox 240x240

  // Marcações radiais do anel externo. 72 traços = um a cada 5 graus, dividido
  // em grupos de 6 para criar os blocos com respiro que o painel original tem.
  const ticks = Array.from({ length: 72 }, (_, i) => {
    const a = (i * 5 * Math.PI) / 180;
    const longo = i % 6 === 0;
    const r1 = longo ? 100 : 106;
    const r2 = 112;
    return (
      <line
        key={i}
        x1={C + Math.cos(a) * r1} y1={C + Math.sin(a) * r1}
        x2={C + Math.cos(a) * r2} y2={C + Math.sin(a) * r2}
        stroke="currentColor"
        strokeWidth={longo ? 2 : 1}
        opacity={longo ? 0.9 : 0.35}
      />
    );
  });

  // Arco por ângulo — os segmentos grossos que giram.
  const arco = (r: number, de: number, ate: number) => {
    const p = (g: number) => [
      C + r * Math.cos((g * Math.PI) / 180),
      C + r * Math.sin((g * Math.PI) / 180),
    ];
    const [x1, y1] = p(de);
    const [x2, y2] = p(ate);
    const grande = ate - de > 180 ? 1 : 0;
    return `M ${x1} ${y1} A ${r} ${r} 0 ${grande} 1 ${x2} ${y2}`;
  };

  const rapido = falando ? 1 : 2.4; // multiplicador de duração: falando = mais rápido

  return (
    // Largura fluida com teto: o painel agora vive numa coluna de 224px, e um
    // HUD de 200px fixos estouraria o padding. `aspectRatio` mantém o círculo
    // redondo em qualquer largura.
    <div style={{
      position: 'relative', width: '100%', maxWidth: 168, aspectRatio: '1',
      color: 'hsl(190 90% 60%)',
    }}>
      <style>{`
        @keyframes jhud-cw  { to { transform: rotate(360deg) } }
        @keyframes jhud-ccw { to { transform: rotate(-360deg) } }
        @keyframes jhud-pulso {
          0%,100% { opacity: .45; transform: scale(.94) }
          50%     { opacity: 1;   transform: scale(1.06) }
        }
        .jhud-gira { transform-origin: 120px 120px; }
        @media (prefers-reduced-motion: reduce) {
          .jhud-gira, .jhud-nucleo { animation: none !important }
        }
      `}</style>

      <svg viewBox="0 0 240 240" width="100%" height="100%"
           style={{ display: 'block', filter: 'drop-shadow(0 0 6px hsl(190 90% 55% / .55))' }}>
        <defs>
          <radialGradient id="jhud-core">
            <stop offset="0%"   stopColor="hsl(190 100% 85%)" stopOpacity=".95" />
            <stop offset="55%"  stopColor="hsl(195 95% 55%)"  stopOpacity=".55" />
            <stop offset="100%" stopColor="hsl(200 90% 45%)"  stopOpacity="0" />
          </radialGradient>
        </defs>

        {/* anel externo com as marcações — gira devagar, sempre */}
        <g className="jhud-gira" style={{ animation: `jhud-cw ${60 * rapido}s linear infinite` }}>
          {ticks}
        </g>
        <circle cx={C} cy={C} r="114" fill="none" stroke="currentColor" strokeWidth="1" opacity=".3" />

        {/* arcos grossos, horário */}
        <g className="jhud-gira" style={{ animation: `jhud-cw ${8 * rapido}s linear infinite` }}>
          <path d={arco(92, -80, 20)} fill="none" stroke="currentColor" strokeWidth="5" opacity=".85" strokeLinecap="round" />
          <path d={arco(92, 110, 170)} fill="none" stroke="currentColor" strokeWidth="5" opacity=".55" strokeLinecap="round" />
          <path d={arco(92, 200, 230)} fill="none" stroke="currentColor" strokeWidth="2" opacity=".9" strokeLinecap="round" />
        </g>

        {/* anel tracejado, anti-horário */}
        <g className="jhud-gira" style={{ animation: `jhud-ccw ${14 * rapido}s linear infinite` }}>
          <circle cx={C} cy={C} r="78" fill="none" stroke="currentColor" strokeWidth="1.5"
                  strokeDasharray="3 7" opacity=".7" />
        </g>

        {/* anel interno segmentado, horário mais rápido */}
        <g className="jhud-gira" style={{ animation: `jhud-cw ${5 * rapido}s linear infinite` }}>
          <path d={arco(62, -40, 60)} fill="none" stroke="currentColor" strokeWidth="8" opacity=".35" />
          <path d={arco(62, 100, 210)} fill="none" stroke="currentColor" strokeWidth="8" opacity=".22" />
        </g>

        {/* raios internos, anti-horário */}
        <g className="jhud-gira" style={{ animation: `jhud-ccw ${20 * rapido}s linear infinite` }}>
          {Array.from({ length: 8 }, (_, i) => {
            const a = (i * 45 * Math.PI) / 180;
            return (
              <line key={i}
                x1={C + Math.cos(a) * 34} y1={C + Math.sin(a) * 34}
                x2={C + Math.cos(a) * 46} y2={C + Math.sin(a) * 46}
                stroke="currentColor" strokeWidth="1.5" opacity=".55" />
            );
          })}
        </g>

        <circle cx={C} cy={C} r="46" fill="none" stroke="currentColor" strokeWidth="1" opacity=".45" />

        {/* núcleo: é ele que marca "está falando" */}
        <circle className="jhud-nucleo" cx={C} cy={C} r="30" fill="url(#jhud-core)"
                style={{
                  transformOrigin: '120px 120px',
                  animation: `jhud-pulso ${falando ? 1.1 : 2.6}s ease-in-out infinite`,
                }} />
        <circle cx={C} cy={C} r="16" fill="none" stroke="currentColor" strokeWidth="1.5" opacity=".8" />
      </svg>
    </div>
  );
};

export const VoiceButton: React.FC = () => {
  const { voiceState, startCall, endCall } = useVoiceCall();
  const [showModal, setShowModal] = useState(false);
  
  const toggleCall = useCallback(() => {
    if (voiceState === 'idle') {
      startCall();
    } else {
      endCall();
    }
  }, [voiceState, startCall, endCall]);
  
  useDesktopIntegration(toggleCall);

  const handleWakeWord = useCallback(() => {
    if (voiceState === 'idle') {
      startCall();
    }
  }, [voiceState, startCall]);

  const { isActive: wakeWordActive, toggleWakeWord } = useWakeWord(handleWakeWord);

  useEffect(() => {
    if (voiceState !== 'idle') {
      setShowModal(true);
    } else {
      setShowModal(false);
    }
  }, [voiceState]);

  return (
    <>
      {/* Voice Controls floating on bottom right */}
      <div style={{
        position: 'fixed',
        bottom: 90,
        right: 24,
        display: 'flex',
        flexDirection: 'column',
        gap: 12,
        zIndex: 50
      }}>
        {/* Wake Word Toggle */}
        <button
          onClick={toggleWakeWord}
          className="neu-btn"
          style={{
            padding: 12,
            borderRadius: '50%',
            background: wakeWordActive ? 'var(--neu-surface)' : 'var(--neu-surface)',
            color: wakeWordActive ? 'hsl(var(--neon-green))' : 'var(--ink-3)',
            boxShadow: wakeWordActive ? 'var(--neu-in-sm)' : 'var(--neu-sm)',
          }}
          title={wakeWordActive ? "Wake word active (Listening for 'Jarvis')" : "Enable wake word"}
        >
          {wakeWordActive ? (
            <svg style={{width: 24, height: 24}} fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z" /></svg>
          ) : (
            <svg style={{width: 24, height: 24}} fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5.586 15H4a1 1 0 01-1-1v-4a1 1 0 011-1h1.586l4.707-4.707C10.923 3.663 12 4.109 12 5v14c0 .891-1.077 1.337-1.707.707L5.586 15z" /><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2" /></svg>
          )}
        </button>

        {/* Main Call Button */}
        <button
          onClick={() => voiceState === 'idle' ? startCall() : endCall()}
          className="neu-btn"
          style={{
            padding: 16,
            borderRadius: '50%',
            background: voiceState === 'idle' ? 'linear-gradient(145deg, var(--accent-soft), var(--accent))' : 'hsl(var(--neon-red))',
            color: 'white',
            boxShadow: voiceState === 'idle' ? 'var(--neu-sm), 0 6px 16px var(--accent-glow)' : 'var(--neu-in-sm)',
            border: 'none'
          }}
        >
          {voiceState === 'idle' ? (
            <svg style={{width: 32, height: 32}} fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" /></svg>
          ) : (
             <svg style={{width: 32, height: 32}} fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" /><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 10a1 1 0 011-1h4a1 1 0 011 1v4a1 1 0 01-1 1h-4a1 1 0 01-1-1v-4z" /></svg>
          )}
        </button>
      </div>

      {/* Full screen modal for active call */}
      {showModal && (
        // ANCORADO NA COLUNA LATERAL, não em tela cheia.
        //
        // Era `position:fixed; inset:0` com backdrop escuro e blur: durante a
        // chamada o chat sumia inteiro. Isso quebra o caso de uso principal —
        // pedir por voz que ele pesquise ou abra algo e ACOMPANHAR o resultado
        // aparecendo no chat. O painel escondia justamente o que a conversa
        // produzia.
        //
        // Agora ele ocupa o espaço vazio da barra lateral, abaixo das abas, e o
        // conteúdo continua inteiro à direita. Sem backdrop, sem blur: nada a
        // obscurecer, porque nada está sendo coberto.
        //
        // O posicionamento mora em `.voice-dock` (industry.css) e não aqui
        // porque depende do breakpoint: no desktop é a coluna de 240px; no
        // mobile, onde essa coluna não existe, vira uma faixa acima da navegação
        // inferior.
        <div className="voice-dock">
          <div className="neu-flat" style={{
            padding: 20, display: 'flex', flexDirection: 'column',
            alignItems: 'center', gap: 12, width: '100%', background: 'var(--neu-bg)'
          }}>
            <h2 style={{ fontSize: 20, fontWeight: 500, color: 'var(--ink)' }}>
              {voiceState === 'connecting' && 'Conectando...'}
              {voiceState === 'listening' && 'Ouvindo...'}
              {voiceState === 'speaking' && 'Jarvis Falando'}
            </h2>
            
            {/* O MESMO HUD nos três estados, mudando só o ritmo. Antes eram dois
                desenhos diferentes (bolinhas girando ao falar, círculos
                concêntricos ao ouvir), e a troca brusca entre eles chamava mais
                atenção que o próprio estado. Um objeto que acelera e desacelera
                lê como uma máquina ligada; dois objetos que se substituem leem
                como um glitch. O rótulo acima já diz o estado por escrito. */}
            <div style={{ width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <JarvisHUD falando={voiceState === 'speaking'} />
            </div>

            <button 
              onClick={endCall}
              className="neu-btn"
              style={{ marginTop: 16, color: 'hsl(var(--neon-red))' }}
            >
              Encerrar
            </button>
          </div>
        </div>
      )}
    </>
  );
};
