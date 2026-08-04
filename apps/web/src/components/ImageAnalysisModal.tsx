import React, { useCallback } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { TransformWrapper, TransformComponent } from 'react-zoom-pan-pinch';
import { X, Maximize2, Minimize2, Save, SlidersHorizontal, Image as ImageIcon } from 'lucide-react';
import { useImageStore } from '../stores/useImageStore';

export default function ImageAnalysisModal() {
  const {
    isOpen,
    isExpanded,
    imageUrl,
    filters,
    closeModal,
    toggleExpand,
    setFilter,
  } = useImageStore();

  const [showFilters, setShowFilters] = React.useState(false);

  const filterStyle = {
    filter: `brightness(${filters.brightness}%) contrast(${filters.contrast}%) saturate(${filters.saturation}%)`,
  };

  const handleSave = useCallback(() => {
    // We emit a custom event to the backend/chat input via a global event or store,
    // or we can simulate a message from the user asking to save it.
    // For now, we dispatch a window event that the Chat component can listen to,
    // or just call an API endpoint.
    window.dispatchEvent(new CustomEvent('jarvis:save_image', {
      detail: { filters }
    }));
  }, [filters]);

  return (
    <AnimatePresence>
      {isOpen && imageUrl && (
        <motion.div
          initial={{ opacity: 0, y: 50, scale: 0.9, x: -20 }}
          animate={{
            opacity: 1,
            y: 0,
            scale: 1,
            x: 0,
            width: isExpanded ? '60vw' : '300px',
            height: isExpanded ? '70vh' : '200px',
            bottom: isExpanded ? '15vh' : '24px',
            left: isExpanded ? '20vw' : '24px',
          }}
          exit={{ opacity: 0, y: 50, scale: 0.9 }}
          transition={{ type: 'spring', damping: 25, stiffness: 200 }}
          className="fixed z-50 flex flex-col bg-slate-900/90 backdrop-blur-md border border-slate-700 rounded-xl shadow-2xl overflow-hidden"
          style={{ 
            boxShadow: '0 20px 40px -10px rgba(0,0,0,0.5)'
          }}
        >
          {/* Header */}
          <div className="flex items-center justify-between p-2 bg-slate-800/80 border-b border-slate-700/50">
            <div className="flex items-center gap-2 text-slate-300 px-2 text-sm font-medium">
              <ImageIcon size={16} className="text-blue-400" />
              <span>Análise Visual</span>
            </div>
            <div className="flex items-center gap-1">
              <button
                onClick={() => setShowFilters(!showFilters)}
                className={`p-1.5 rounded-md hover:bg-slate-700 transition-colors ${showFilters ? 'bg-slate-700 text-blue-400' : 'text-slate-400'}`}
                title="Ajustes de Imagem"
              >
                <SlidersHorizontal size={16} />
              </button>
              <button
                onClick={toggleExpand}
                className="p-1.5 rounded-md text-slate-400 hover:bg-slate-700 hover:text-slate-200 transition-colors"
                title={isExpanded ? "Minimizar" : "Expandir"}
              >
                {isExpanded ? <Minimize2 size={16} /> : <Maximize2 size={16} />}
              </button>
              <button
                onClick={closeModal}
                className="p-1.5 rounded-md text-slate-400 hover:bg-red-500/20 hover:text-red-400 transition-colors"
              >
                <X size={16} />
              </button>
            </div>
          </div>

          {/* Body */}
          <div className="flex-1 relative bg-black/50 overflow-hidden flex">
            {/* Image Viewer */}
            <div className="flex-1 overflow-hidden relative">
              <TransformWrapper
                initialScale={1}
                minScale={0.5}
                maxScale={5}
                centerOnInit
              >
                <TransformComponent wrapperClass="!w-full !h-full" contentClass="!w-full !h-full flex items-center justify-center">
                  <img
                    src={imageUrl}
                    alt="Jarvis Analysis"
                    className="max-w-full max-h-full object-contain pointer-events-none"
                    style={filterStyle}
                  />
                </TransformComponent>
              </TransformWrapper>
            </div>

            {/* Filters Sidebar (Animated) */}
            <AnimatePresence>
              {showFilters && (
                <motion.div
                  initial={{ width: 0, opacity: 0 }}
                  animate={{ width: 220, opacity: 1 }}
                  exit={{ width: 0, opacity: 0 }}
                  className="bg-slate-800/90 border-l border-slate-700 flex flex-col p-4 gap-4 overflow-hidden"
                >
                  <div className="text-sm font-medium text-slate-200 mb-2 whitespace-nowrap">Filtros de Imagem</div>
                  
                  <div className="flex flex-col gap-1.5">
                    <label className="text-xs text-slate-400 flex justify-between">
                      <span>Brilho</span>
                      <span>{filters.brightness}%</span>
                    </label>
                    <input
                      type="range"
                      min="0"
                      max="200"
                      value={filters.brightness}
                      onChange={(e) => setFilter('brightness', Number(e.target.value))}
                      className="w-full accent-blue-500"
                    />
                  </div>

                  <div className="flex flex-col gap-1.5">
                    <label className="text-xs text-slate-400 flex justify-between">
                      <span>Contraste</span>
                      <span>{filters.contrast}%</span>
                    </label>
                    <input
                      type="range"
                      min="0"
                      max="200"
                      value={filters.contrast}
                      onChange={(e) => setFilter('contrast', Number(e.target.value))}
                      className="w-full accent-blue-500"
                    />
                  </div>

                  <div className="flex flex-col gap-1.5">
                    <label className="text-xs text-slate-400 flex justify-between">
                      <span>Saturação</span>
                      <span>{filters.saturation}%</span>
                    </label>
                    <input
                      type="range"
                      min="0"
                      max="200"
                      value={filters.saturation}
                      onChange={(e) => setFilter('saturation', Number(e.target.value))}
                      className="w-full accent-blue-500"
                    />
                  </div>

                  <div className="mt-auto pt-4">
                    <button
                      onClick={handleSave}
                      className="w-full flex items-center justify-center gap-2 bg-blue-600 hover:bg-blue-500 text-white text-sm py-2 px-3 rounded-lg transition-colors shadow-lg shadow-blue-500/20 whitespace-nowrap"
                    >
                      <Save size={16} />
                      Salvar Imagem
                    </button>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
