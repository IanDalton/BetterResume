import React, { useRef, useState } from 'react';
import { useI18n } from '../i18n';
import { uploadProfilePicture } from '../services';

interface ProfilePictureUploaderProps {
  userId: string;
  include: boolean;
  onIncludeChange: (value: boolean) => void;
  imageUrl: string | null;
  onUploaded: () => void;
}

export const ProfilePictureUploader: React.FC<ProfilePictureUploaderProps> = ({
  userId,
  include,
  onIncludeChange,
  imageUrl,
  onUploaded,
}) => {
  const { t } = useI18n();
  const inputRef = useRef<HTMLInputElement | null>(null);
  const [uploading, setUploading] = useState(false);
  const [status, setStatus] = useState<string | null>(null);

  const triggerFileSelect = () => {
    setStatus(null);
    inputRef.current?.click();
  };

  const handleFileChange = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    if (file.size > 5 * 1024 * 1024) {
      setStatus(t('profile.error.size'));
      event.target.value = '';
      return;
    }
    setUploading(true);
    setStatus(null);
    try {
      await uploadProfilePicture(userId, file);
      setStatus(t('profile.upload.success'));
      onUploaded();
    } catch (error: any) {
      const message = error instanceof Error && error.message ? error.message : t('profile.upload.error');
      setStatus(message);
    } finally {
      setUploading(false);
      event.target.value = '';
    }
  };

  return (
    <section className="mb-10">
      <h2 className="text-xl font-semibold mb-4">{t('profile.section.title')}</h2>
      <div className="flex flex-col sm:flex-row gap-4 sm:items-center">
        <div className="w-28 h-28 rounded-lg border border-neutral-300 dark:border-neutral-700 bg-neutral-100 dark:bg-neutral-900 flex items-center justify-center overflow-hidden">
          {imageUrl ? (
            <img src={imageUrl} alt={t('profile.section.title')} className="w-full h-full object-cover" />
          ) : (
            <span className="text-xs text-neutral-500 text-center px-2">{t('profile.none')}</span>
          )}
        </div>
        <div className="flex-1 flex flex-col gap-2">
          <div className="flex flex-wrap gap-2 items-center">
            <button type="button" className="btn-secondary btn-sm" onClick={triggerFileSelect} disabled={uploading}>
              {uploading ? t('profile.uploading') : t('profile.upload')}
            </button>
            <label className="flex items-center gap-2 text-sm text-neutral-700 dark:text-neutral-300">
              <input
                type="checkbox"
                className="h-4 w-4"
                checked={include && !!imageUrl}
                onChange={e => onIncludeChange(e.target.checked)}
                disabled={!imageUrl}
              />
              <span>{t('profile.toggle')}</span>
            </label>
          </div>
          <p className="text-xs text-neutral-500 dark:text-neutral-400">{t('profile.upload.hint')}</p>
          {!imageUrl && (
            <p className="text-xs text-neutral-500 dark:text-neutral-500">{t('profile.toggle.disabled')}</p>
          )}
          {status && (
            <p className="text-xs text-neutral-500 dark:text-neutral-400">{status}</p>
          )}
        </div>
      </div>
      <input
        ref={inputRef}
        type="file"
        accept="image/png,image/jpeg"
        className="hidden"
        onChange={handleFileChange}
      />
    </section>
  );
};
