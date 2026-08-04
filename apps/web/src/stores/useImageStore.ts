import { create } from 'zustand'

interface ImageState {
  isOpen: boolean
  isExpanded: boolean
  imageUrl: string | null
  filters: {
    brightness: number
    contrast: number
    saturation: number
  }
  openModal: (url: string) => void
  closeModal: () => void
  toggleExpand: () => void
  setFilter: (filter: 'brightness' | 'contrast' | 'saturation', value: number) => void
  resetFilters: () => void
}

const defaultFilters = {
  brightness: 100,
  contrast: 100,
  saturation: 100,
}

export const useImageStore = create<ImageState>((set) => ({
  isOpen: false,
  isExpanded: false,
  imageUrl: null,
  filters: { ...defaultFilters },

  openModal: (url) => set({ isOpen: true, imageUrl: url, isExpanded: false, filters: { ...defaultFilters } }),
  closeModal: () => set({ isOpen: false, imageUrl: null }),
  toggleExpand: () => set((state) => ({ isExpanded: !state.isExpanded })),
  setFilter: (filter, value) =>
    set((state) => ({
      filters: {
        ...state.filters,
        [filter]: value,
      },
    })),
  resetFilters: () => set({ filters: { ...defaultFilters } }),
}))
