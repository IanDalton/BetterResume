import { describe, expect, it } from 'vitest';
import { buildCsvFromEntries, buildJobsFromEntries } from '../csv';
import type { ResumeEntry } from '../../types';

const jobEntry: ResumeEntry = {
  type: 'job',
  company: 'Acme Corp',
  location: 'Remote',
  role: 'Engineer',
  start: '3/2021',
  end: 'Present',
  description: 'Built APIs',
  role_description: 'Led team',
};

describe('buildCsvFromEntries', () => {
  it('emits the backend jobs.csv header', () => {
    const csv = buildCsvFromEntries([]);
    expect(csv).toBe('type,company,location,role,start_date,end_date,description');
  });

  it('normalizes MM/YYYY dates and present markers', () => {
    const csv = buildCsvFromEntries([jobEntry]);
    const row = csv.split('\n')[1];
    expect(row).toContain('01/03/2021');
    expect(row).toContain('present');
  });

  it('quotes values containing commas or newlines', () => {
    const csv = buildCsvFromEntries([{ ...jobEntry, company: 'Acme, Inc', role_description: '' }]);
    expect(csv).toContain('"Acme, Inc"');
    // description + role_description joined with newline must be quoted
    const multi = buildCsvFromEntries([jobEntry]);
    expect(multi).toContain('"Built APIs\nLed team"');
  });

  it('maps info entries: role becomes the key column', () => {
    const csv = buildCsvFromEntries([
      { type: 'info', company: '', location: '', role: 'email', start: '', end: '', description: 'a@b.c', role_description: '' },
    ]);
    const row = csv.split('\n')[1];
    expect(row.startsWith('info,email,')).toBe(true);
  });
});

describe('buildJobsFromEntries', () => {
  it('produces backend JobRecord-shaped objects', () => {
    const jobs = buildJobsFromEntries([jobEntry]);
    expect(jobs).toEqual([
      {
        type: 'job',
        company: 'Acme Corp',
        location: 'Remote',
        role: 'Engineer',
        start_date: '01/03/2021',
        end_date: 'present',
        description: 'Built APIs\nLed team',
      },
    ]);
  });

  it('skips unknown entry types', () => {
    const jobs = buildJobsFromEntries([{ ...jobEntry, type: 'mystery' as any }]);
    expect(jobs).toEqual([]);
  });

  it('normalizes YYYY/MM dates', () => {
    const jobs = buildJobsFromEntries([{ ...jobEntry, start: '2021-03' }]);
    expect(jobs[0].start_date).toBe('01/03/2021');
  });
});
