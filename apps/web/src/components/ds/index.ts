/*
 * Barrel dos primitivos do design system "Industry" (Plano A, fase D1).
 *
 * O CSS extra e importado aqui, e nao em cada componente: importar de qualquer
 * primitivo ja garante o estilo, e ha um unico ponto de entrada para a ordem
 * das folhas. Os tokens em si (styles/industry.css) NAO sao importados daqui —
 * eles pertencem a camada de fundacao (D0) e sao carregados pelo app.
 */
import './ds.css';

export { Panel } from './Panel';
export type { PanelProps } from './Panel';

export { Readout } from './Readout';
export type { ReadoutProps, ReadoutTone } from './Readout';

export { Stat } from './Stat';
export type { StatProps, StatTone } from './Stat';

export { Meter } from './Meter';
export type { MeterProps } from './Meter';

export { Tag } from './Tag';
export type { TagProps, TagTone } from './Tag';

export { Btn } from './Btn';
export type { BtnProps, BtnVariant } from './Btn';

export { Field, Input } from './Field';
export type { FieldProps, FieldControlProps, InputProps } from './Field';

export { DataTable } from './DataTable';
export type { DataTableProps, DataTableColumn, DataTableAlign } from './DataTable';

export { Feed } from './Feed';
export type { FeedProps, FeedEvent, FeedTone } from './Feed';

export { Dialog } from './Dialog';
export type { DialogProps } from './Dialog';
