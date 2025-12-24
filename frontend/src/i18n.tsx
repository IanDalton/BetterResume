import React, { createContext, useCallback, useContext, useMemo, useState, useEffect } from 'react';

export type Language = 'en' | 'es';

type Dict = Record<string, string>;

const dictionaries: Record<Language, Dict> = {
  en: {
    'app.title': 'Better Resume',
    'app.tagline': 'Made for humans, optimized for machines.',
  'app.meta.description': 'Better Resume – Made for humans, optimized for machines.',
  'app.language': 'Language',
    'user.id': 'User ID',
    'format': 'Format',
  'format.latex': 'LaTeX',
  'format.word': 'Word',
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
  'button.clear': 'Clear All',
  'confirm.clear': 'This will remove all locally saved progress. Continue?',
    'entries.none': 'No entries yet.',
    'entry.edit': 'Edit',
    'entry.delete': 'Del',
    'present': 'Present',
    'profile.section.title': 'Profile Picture',
    'profile.upload': 'Select photo',
    'profile.uploading': 'Uploading…',
    'profile.upload.hint': 'PNG or JPG up to 5 MB. You can crop it before saving.',
    'profile.none': 'No picture uploaded yet.',
    'profile.upload.success': 'Photo uploaded successfully.',
    'profile.upload.refreshError': 'Photo uploaded but preview could not refresh. Please try again.',
    'profile.upload.error': 'Failed to upload photo.',
    'profile.error.size': 'Image must be smaller than 5 MB.',
    'profile.toggle': 'Include profile picture when generating resumes',
    'profile.toggle.disabled': 'Upload a photo to enable this option.',
    'profile.editing.modalTitle': 'Crop your profile photo',
    'profile.editing.subtitle': 'Drag the photo to center yourself, then zoom and choose the shape before saving.',
    'profile.editing.zoom': 'Zoom',
    'profile.editing.zoomIn': 'Zoom in',
    'profile.editing.zoomOut': 'Zoom out',
    'profile.editing.shapeLabel': 'Shape',
    'profile.editing.gestureHint': 'Drag to reposition, pinch or scroll to zoom, or use the slider below.',
    'profile.editing.reset': 'Reset position',
    'profile.editing.save': 'Save photo',
    'profile.editing.cancel': 'Cancel',
    'profile.shape.square': 'Square',
    'profile.shape.circle': 'Circle',
    'json.show': 'Show JSON output',
  'json.hide': 'Hide JSON output',
  'json.title': 'Resume JSON',
  'preview.title': 'Preview',
  'preview.pdf.unavailable': 'PDF not available',
  'download.pdf': 'Download PDF',
  'download.source': 'Edit (Download Source)',
  'download.downloading': 'Downloading…',
  'download.preparing': 'Preparing…',
  'modal.building.title': 'Building your resume…',
  'modal.building.subtitle': 'AI is assembling sections and formatting',
  'modal.building.hide': 'Hide (continues in background)',
  'progress.starting': 'starting',
  'donate.title': 'Enjoying BetterResume?',
  'donate.body': "You've generated 5 resumes. If this tool saved you time, consider supporting development with a small donation. It helps cover infrastructure & continued improvements.",
  'donate.cta': 'Donate',
  'donate.later': 'Maybe Later',
  'donate.footer': 'We only show this once at 5 resumes. Thank you for using the app!',
  'wizard.back': 'Back',
  'wizard.next': 'Next',
  'wizard.finish': 'Finish Onboarding',
  'wizard.stage.personal': 'Personal',
  'wizard.stage.education': 'Education',
  'wizard.stage.experience': 'Experience',
  'wizard.stage.review': 'Review',
  'wizard.personal.fullName': 'Full Name',
  'wizard.personal.email': 'Email',
  'wizard.personal.phone': 'Phone',
  'wizard.personal.address': 'Location',
  'wizard.personal.websites': 'Websites / Profiles',
  'wizard.personal.label': 'Label',
  'wizard.personal.add': 'Add',
  'wizard.personal.remove': 'Remove',
  'wizard.personal.help': 'Add as many personal / professional links as you like (portfolio, GitHub, LinkedIn, etc.). Each link can have its own label.',
  'education.degree.placeholder': 'Degree / Program',
  'education.institution.placeholder': 'Institution',
  'education.location.placeholder': 'Location',
  'education.start.placeholder': 'Start',
  'education.end.placeholder': 'End / Present',
  'education.description.placeholder': 'Description / Achievements',
  'education.add': 'Add Education',
  'experience.role.placeholder': 'Role / Title',
  'experience.company.placeholder': 'Company / Org',
  'experience.location.placeholder': 'Location',
  'experience.start.placeholder': 'Start',
  'experience.end.placeholder': 'End / Present',
  'experience.description.placeholder': 'Description / Impact',
  'experience.add': 'Add Experience',
  'review.title': 'Review',
  'review.body': "Quick summary of what you've added. You can finish to access full dashboard and make further edits.",
  'auth.welcome': 'Welcome',
  'auth.tagline': 'Create an account to save your resumes across devices. Or continue as a guest (local only).',
  'auth.email': 'Email',
  'auth.password': 'Password',
  'auth.needAccount': 'Need an account? Sign up',
  'auth.haveAccount': 'Have an account? Sign in',
  'auth.signIn': 'Sign In',
  'auth.createAccount': 'Create Account',
  'auth.or': 'or',
  'auth.continueGoogle': 'Continue with Google',
  'auth.working': 'Working...',
  'auth.guest.notice': 'Guest sessions use a random ID stored only in this browser. Clearing site data or switching devices will lose your resumes.',
  'auth.logout': 'Logout',
  'auth.guest': 'Guest',
  'auth.error.generic': 'Auth failed',
  'auth.error.google': 'Google sign-in failed',
  'auth.error.guest': 'Guest sign-in failed',
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
  ,
  // Guide modal
  'guide.title': 'Welcome to Better resume',
  'guide.intro': 'Quick guide to tailor your resume for a specific role:',
  'guide.step1': 'Paste the target job description into the Job Description box (you can copy it directly from a LinkedIn job post).',
  'guide.step2': 'Add your details and experience in the entry section above. Keep bullets action‑oriented and measurable.',
  'guide.step3': 'Choose your preferred format (Word or LaTeX), then click Generate Resume.',
  'guide.step4': 'Review the preview, then download the PDF and/or source.',
  'guide.tip': 'Tip: For best results, match keywords from the job post (skills, tools, responsibilities) in your entries.',
  'guide.gotIt': 'Got it',
  'guide.button.title': 'Quick guide',
  // Footer
  'footer.brandline': 'Better resume — a tool made by Ian Dalton'
  ,
  // Donation toast
  'donate.toast.title': 'Help keep it free',
  'donate.toast.body': 'Traffic grew a lot. A small donation (~$5,000 ARS, less than a hamburger) helps keep the servers running and this tool free.',
  'donate.toast.cta': 'Donate',
  'donate.toast.dismiss': 'Not now',
  // Stripe donation
  'donate.stripe.title': 'Help Keep BetterResume Free',
  'donate.stripe.body.international': 'If this tool saved you time, consider supporting development with a small donation. Payments are processed securely via Stripe.',
  'donate.stripe.body.argentina': 'Si te resultó útil, considera hacer una pequeña donación para mantener el proyecto en funcionamiento. Pagos seguros con Stripe.',
  'donate.stripe.cta': 'Donate via Stripe',
  'donate.error': 'Failed to process donation. Please try again.'
  },
  es: {
    'app.title': 'Better Resume',
    'app.tagline': 'Hecho para humanos, optimizado para máquinas.',
  'app.meta.description': 'Better Resume – Hecho para humanos, optimizado para máquinas.',
  'app.language': 'Idioma',
    'user.id': 'ID de Usuario',
    'format': 'Formato',
  'format.latex': 'LaTeX',
  'format.word': 'Word',
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
  'button.clear': 'Borrar Todo',
  'confirm.clear': 'Esto eliminará el progreso local guardado. ¿Continuar?',
    'entries.none': 'Sin entradas todavía.',
    'entry.edit': 'Editar',
    'entry.delete': 'Borrar',
    'present': 'Actual',
    'profile.section.title': 'Foto de perfil',
    'profile.upload': 'Elegir foto',
    'profile.uploading': 'Subiendo…',
    'profile.upload.hint': 'PNG o JPG de hasta 5 MB. Podrás recortarla antes de guardar.',
    'profile.none': 'Aún no subiste una foto.',
    'profile.upload.success': 'Foto cargada correctamente.',
    'profile.upload.refreshError': 'La foto se cargó pero no se pudo actualizar la vista previa. Vuelve a intentarlo.',
    'profile.upload.error': 'No se pudo subir la foto.',
    'profile.error.size': 'La imagen debe pesar menos de 5 MB.',
    'profile.toggle': 'Incluir la foto al generar el CV',
    'profile.toggle.disabled': 'Sube una foto para habilitar esta opción.',
    'profile.editing.modalTitle': 'Recorta tu foto de perfil',
    'profile.editing.subtitle': 'Arrastra la foto para centrarte, ajusta el zoom y elige la forma antes de guardar.',
    'profile.editing.zoom': 'Zoom',
    'profile.editing.zoomIn': 'Acercar',
    'profile.editing.zoomOut': 'Alejar',
    'profile.editing.shapeLabel': 'Forma',
    'profile.editing.gestureHint': 'Arrastra para recolocar, pellizca o usa la rueda para hacer zoom, o ajusta el control deslizante.',
    'profile.editing.reset': 'Restablecer posición',
    'profile.editing.save': 'Guardar foto',
    'profile.editing.cancel': 'Cancelar',
    'profile.shape.square': 'Cuadrada',
    'profile.shape.circle': 'Circular',
  'json.show': 'Mostrar salida JSON',
  'json.hide': 'Ocultar salida JSON',
  'json.title': 'JSON del Currículum',
  'preview.title': 'Vista previa',
  'preview.pdf.unavailable': 'PDF no disponible',
  'download.pdf': 'Descargar PDF',
  'download.source': 'Editar (Descargar fuente)',
  'download.downloading': 'Descargando…',
  'download.preparing': 'Preparando…',
  'modal.building.title': 'Construyendo tu currículum…',
  'modal.building.subtitle': 'La IA está ensamblando secciones y formato',
  'modal.building.hide': 'Ocultar (continúa en segundo plano)',
  'progress.starting': 'iniciando',
  'donate.title': '¿Disfrutando BetterResume?',
  'donate.body': 'Has generado 5 currículums. Si esta herramienta te ahorró tiempo, considera apoyar el desarrollo con una pequeña donación. Ayuda a cubrir infraestructura y mejoras continuas.',
  'donate.cta': 'Donar',
  'donate.later': 'Quizás después',
  'donate.footer': 'Mostramos esto solo una vez al llegar a 5 currículums. ¡Gracias por usar la aplicación!',
  'wizard.back': 'Atrás',
  'wizard.next': 'Siguiente',
  'wizard.finish': 'Finalizar',
  'wizard.stage.personal': 'Personal',
  'wizard.stage.education': 'Educación',
  'wizard.stage.experience': 'Experiencia',
  'wizard.stage.review': 'Revisión',
  'wizard.personal.fullName': 'Nombre completo',
  'wizard.personal.email': 'Correo',
  'wizard.personal.phone': 'Teléfono',
  'wizard.personal.address': 'Ubicación',
  'wizard.personal.websites': 'Sitios / Perfiles',
  'wizard.personal.label': 'Etiqueta',
  'wizard.personal.add': 'Agregar',
  'wizard.personal.remove': 'Quitar',
  'wizard.personal.help': 'Agrega los enlaces personales/profesionales que quieras (portafolio, GitHub, LinkedIn, etc.). Cada enlace puede tener su propia etiqueta.',
  'education.degree.placeholder': 'Título / Programa',
  'education.institution.placeholder': 'Institución',
  'education.location.placeholder': 'Ubicación',
  'education.start.placeholder': 'Inicio',
  'education.end.placeholder': 'Fin / Actual',
  'education.description.placeholder': 'Descripción / Logros',
  'education.add': 'Agregar Educación',
  'experience.role.placeholder': 'Rol / Título',
  'experience.company.placeholder': 'Empresa / Org',
  'experience.location.placeholder': 'Ubicación',
  'experience.start.placeholder': 'Inicio',
  'experience.end.placeholder': 'Fin / Actual',
  'experience.description.placeholder': 'Descripción / Impacto',
  'experience.add': 'Agregar Experiencia',
  'review.title': 'Revisión',
  'review.body': 'Resumen rápido de lo que añadiste. Puedes finalizar para acceder al panel y seguir editando.',
  'auth.welcome': 'Bienvenido',
  'auth.tagline': 'Crea una cuenta para guardar tus currículums entre dispositivos. O continúa como invitado (solo local).',
  'auth.email': 'Correo',
  'auth.password': 'Contraseña',
  'auth.needAccount': '¿Necesitas una cuenta? Regístrate',
  'auth.haveAccount': '¿Tienes una cuenta? Inicia sesión',
  'auth.signIn': 'Iniciar Sesión',
  'auth.createAccount': 'Crear Cuenta',
  'auth.or': 'o',
  'auth.continueGoogle': 'Continuar con Google',
  'auth.working': 'Trabajando...',
  'auth.guest.notice': 'Las sesiones de invitado usan un ID aleatorio solo en este navegador. Limpiar datos o cambiar de dispositivo perderá tus currículums.',
  'auth.logout': 'Cerrar Sesión',
  'auth.guest': 'Invitado',
  'auth.error.generic': 'Fallo de autenticación',
  'auth.error.google': 'Fallo con Google',
  'auth.error.guest': 'Fallo al entrar como invitado',
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
  ,
  // Guide modal
  'guide.title': 'Bienvenido a Better resume',
  'guide.intro': 'Guía rápida para adaptar tu currículum a un puesto específico:',
  'guide.step1': 'Pega la descripción del puesto objetivo en el cuadro de Descripción del Puesto (puedes copiarla directamente de una oferta en LinkedIn).',
  'guide.step2': 'Añade tus datos y experiencia en la sección de entradas de arriba. Mantén los puntos orientados a la acción y medibles.',
  'guide.step3': 'Elige tu formato preferido (Word o LaTeX) y haz clic en Generar Currículum.',
  'guide.step4': 'Revisa la vista previa y luego descarga el PDF y/o la fuente.',
  'guide.tip': 'Consejo: Para mejores resultados, incluye palabras clave de la oferta (habilidades, herramientas, responsabilidades) en tus entradas.',
  'guide.gotIt': 'Entendido',
  'guide.button.title': 'Guía rápida',
  // Footer
  'footer.brandline': 'Better resume — una herramienta creada por Ian Dalton'
  ,
  // Donation toast
  'donate.toast.title': 'Ayúdanos a mantenerlo gratis',
  'donate.toast.body': 'El tráfico creció mucho. Una pequeña donación (~$5.000 ARS, menos que una hamburguesa) ayuda a mantener el servidor y esta herramienta gratis.',
  'donate.toast.cta': 'Donar',
  'donate.toast.dismiss': 'Ahora no',
  // Stripe donation
  'donate.stripe.title': 'Ayúdanos a mantener BetterResume gratis',
  'donate.stripe.body.international': 'Si te resultó útil, considera apoyar el desarrollo con una pequeña donación. Pagos seguros a través de Stripe.',
  'donate.stripe.body.argentina': 'Si te resultó útil, considera hacer una pequeña donación para mantener el proyecto en funcionamiento. Pagos seguros con Stripe.',
  'donate.stripe.cta': 'Donar con Stripe',
  'donate.error': 'Falló al procesar la donación. Por favor, intenta de nuevo.'
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
    if (stored && (stored in dictionaries)) return stored;
    const supported = Object.keys(dictionaries);
    if (typeof navigator !== 'undefined') {
      const nav: any = navigator;
      const candidates: string[] = [];
      if (nav.languages) candidates.push(...nav.languages);
      if (navigator.language) candidates.push(navigator.language);
      for (const raw of candidates) {
        if (!raw) continue;
        const base = raw.toLowerCase().split('-')[0];
        const match = supported.find(s => s === base);
        if (match) return match as Language;
      }
    }
  } catch {/* ignore */}
  return 'en'; // default fallback
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

  // If user hasn't explicitly chosen (no stored lang), respond to system/browser language changes.
  useEffect(() => {
    if (localStorage.getItem('lang')) return; // respect explicit choice
    const handler = () => {
      const detected = detectInitialLang();
      setLangState(detected);
    };
    window.addEventListener('languagechange', handler);
    return () => window.removeEventListener('languagechange', handler);
  }, []);

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
