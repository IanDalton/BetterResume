import React, { createContext, useCallback, useContext, useMemo, useState, useEffect } from 'react';

export type Language = 'en' | 'es';

type Dict = Record<string, string>;

const dictionaries: Record<Language, Dict> = {
  en: {
    'app.title': 'Better Resume',
    'app.tagline': 'Create your resume easily and quickly.',
    'user.id': 'User ID',
    'format': 'Format',
    'job.description.section': 'Target Job Description',
    'job.description.placeholder': 'Paste job description here...',
    'upload.jobs': 'Upload jobs.csv',
    'generate.resume': 'Generate Resume',
    'working': 'Working...',
    'add.entry.section': 'Add Entry',
    'field.type': 'Type',
    'type.info': 'Personal Info',
    'type.education': 'Education',
    'type.job': 'Job',
    'type.non-profit': 'Non-Profit',
    'type.project': 'Project',
    'type.contract': 'Contract',
    'type.part-time': 'Part-Time',
    'field.company': 'Company',
    'field.location': 'Location',
    'field.role': 'Role / Field',
    'field.start': 'Start',
    'field.end': 'End',
    'field.description': 'Description',
    'field.extraDetails': 'Extra Details',
    'placeholder.company': 'Acme Corp',
    'placeholder.location': 'City, Country',
    'placeholder.role': 'Role',
    'placeholder.start': 'MM/YYYY',
    'placeholder.end': 'MM/YYYY or Present',
    'placeholder.description': 'Details...',
    'placeholder.extraDetails': 'When applicable...',
    'button.cancel': 'Cancel',
    'button.addEntry': 'Add Entry',
    'button.updateEntry': 'Update Entry',
    'entries.none': 'No entries yet.',
    'entry.edit': 'Edit',
    'entry.delete': 'Del',
    'present': 'Present',
    'jobs.none': 'No jobs added yet.',
    'jobs.title': 'Title',
    'jobs.company': 'Company',
    'jobs.start': 'Start',
    'jobs.end': 'End',
    'jobs.description': 'Description',
    'jobs.actions': 'Actions',
    'jobs.remove': 'Remove',
    'lang.english': 'English',
    'lang.spanish': 'Spanish',
    'field.personal.name': 'name',
    'field.personal.email': 'email',
    'field.personal.phone': 'phone',
    'field.personal.website': 'website',
    'field.personal.address': 'address'
  },
  es: {
    'app.title': 'Better Resume',
    'app.tagline': 'Crea tu currículum de manera fácil y rápida.',
    'user.id': 'ID de Usuario',
    'format': 'Formato',
    'job.description.section': 'Descripción del Puesto Objetivo',
    'job.description.placeholder': 'Pega aquí la descripción del puesto...',
    'upload.jobs': 'Subir jobs.csv',
    'generate.resume': 'Generar Currículum',
    'working': 'Trabajando...',
    'add.entry.section': 'Agregar Entrada',
    'field.type': 'Tipo',
    'type.info': 'Información Personal',
    'type.education': 'Educación',
    'type.job': 'Trabajo',
    'type.non-profit': 'ONG',
    'type.project': 'Proyecto',
    'type.contract': 'Contrato',
    'type.part-time': 'Medio Tiempo',
    'field.company': 'Empresa',
    'field.location': 'Ubicación',
    'field.role': 'Cargo / Campo',
    'field.start': 'Inicio',
    'field.end': 'Fin',
    'field.description': 'Descripción',
    'field.extraDetails': 'Detalles Extra',
    'placeholder.company': 'Ej: Acme Corp',
    'placeholder.location': 'Ciudad, País',
    'placeholder.role': 'Cargo',
    'placeholder.start': 'MM/AAAA',
    'placeholder.end': 'MM/AAAA o Actual',
    'placeholder.description': 'Detalles...',
    'placeholder.extraDetails': 'Cuando corresponda...',
    'button.cancel': 'Cancelar',
    'button.addEntry': 'Agregar Entrada',
    'button.updateEntry': 'Actualizar Entrada',
    'entries.none': 'Sin entradas todavía.',
    'entry.edit': 'Editar',
    'entry.delete': 'Borrar',
    'present': 'Actual',
    'jobs.none': 'Aún no se agregaron trabajos.',
    'jobs.title': 'Título',
    'jobs.company': 'Empresa',
    'jobs.start': 'Inicio',
    'jobs.end': 'Fin',
    'jobs.description': 'Descripción',
    'jobs.actions': 'Acciones',
    'jobs.remove': 'Quitar',
    'lang.english': 'Inglés',
    'lang.spanish': 'Español',
    'field.personal.name': 'nombre',
    'field.personal.email': 'correo',
    'field.personal.phone': 'teléfono',
    'field.personal.website': 'sitio web',
    'field.personal.address': 'dirección'
  }
};

interface I18nContextValue {
  lang: Language;
  setLang: (l: Language) => void;
  t: (key: string) => string;
}

const I18nContext = createContext<I18nContextValue | undefined>(undefined);

function detectInitialLang(): Language {
  try {
    const stored = localStorage.getItem('lang') as Language | null;
    if (stored && ['en','es'].includes(stored)) return stored;
    if (typeof navigator !== 'undefined') {
      const candidates: string[] = [];
      if ((navigator as any).languages) candidates.push(...(navigator as any).languages);
      if (navigator.language) candidates.push(navigator.language);
      for (const raw of candidates) {
        if (!raw) continue;
        const code = raw.toLowerCase();
        if (code.startsWith('es')) return 'es';
        if (code.startsWith('en')) return 'en';
      }
    }
  } catch {/* ignore */}
  return 'en';
}

export const I18nProvider: React.FC<{children: React.ReactNode}> = ({ children }) => {
  const [lang, setLangState] = useState<Language>(() => detectInitialLang());

  const setLang = useCallback((l: Language) => {
    setLangState(l);
    localStorage.setItem('lang', l);
  }, []);

  const t = useCallback((key: string) => {
    const dict = dictionaries[lang];
    return dict[key] || dictionaries.en[key] || key;
  }, [lang]);

  useEffect(() => {
    try { document.documentElement.lang = lang; } catch {/* ignore */}
  }, [lang]);

  const value = useMemo(() => ({ lang, setLang, t }), [lang, setLang, t]);
  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
};

export function useI18n() {
  const ctx = useContext(I18nContext);
  if (!ctx) throw new Error('useI18n must be used within I18nProvider');
  return ctx;
}

export const availableLanguages: { code: Language; labelKey: string }[] = [
  { code: 'en', labelKey: 'lang.english' },
  { code: 'es', labelKey: 'lang.spanish' }
];
