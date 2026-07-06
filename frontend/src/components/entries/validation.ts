import { z } from 'zod';

export const personalInfoSchema = z.object({
  fullName: z.string().trim().min(1, 'Full name is required'),
  email: z.string().trim().min(1, 'Email is required').email('Enter a valid email address'),
  phone: z.string().optional(),
  address: z.string().optional(),
});

const MONTH_YEAR = /^(0[1-9]|1[0-2])\/\d{4}$/;
const monthYearOrPresent = z
  .string()
  .optional()
  .refine((v) => !v || v.toLowerCase() === 'present' || MONTH_YEAR.test(v), {
    message: 'Use the date picker or leave blank',
  });

export const educationEntrySchema = z.object({
  type: z.enum(['education', 'certification']),
  company: z.string().trim().min(1, 'Institution is required'),
  role: z.string().trim().min(1, 'Degree is required'),
  location: z.string().optional(),
  start: monthYearOrPresent,
  end: monthYearOrPresent,
  description: z.string().optional(),
});

export const experienceEntrySchema = z.object({
  type: z.enum(['job', 'contract', 'part-time', 'project', 'non-profit']),
  company: z.string().trim().min(1, 'Company is required'),
  role: z.string().trim().min(1, 'Role is required'),
  location: z.string().optional(),
  start: monthYearOrPresent,
  end: monthYearOrPresent,
  description: z.string().optional(),
});

export const languageEntrySchema = z.object({
  name: z.string().trim().min(1, 'Language name is required'),
  proficiency: z.string().trim().min(1, 'Select a proficiency level'),
});
