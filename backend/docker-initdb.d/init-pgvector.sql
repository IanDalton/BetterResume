-- Create pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- Table for storing user resume text + embeddings
CREATE TABLE IF NOT EXISTS resume_vectors (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  content TEXT,
  embedding vector(768)
);

-- IVFFLAT index for ANN search. Tune lists for your dataset; 100 is a reasonable start.
CREATE INDEX IF NOT EXISTS idx_resume_vectors_embedding
ON resume_vectors USING ivfflat (embedding) WITH (lists = 100);

-- Users table
CREATE TABLE IF NOT EXISTS users (
  user_id TEXT PRIMARY KEY,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Resume requests table
CREATE TABLE IF NOT EXISTS resume_requests (
  id BIGSERIAL PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
  job_posting TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Job experiences table
CREATE TABLE IF NOT EXISTS job_experiences (
  id BIGSERIAL PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
  company TEXT NOT NULL,
  description TEXT NOT NULL,
  type TEXT NOT NULL,
  role TEXT,
  location TEXT,
  start_date TEXT,
  end_date TEXT,
  raw JSONB,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Table for storing user files (CSVs, images, generated resumes)
CREATE TABLE IF NOT EXISTS user_files (
    user_id TEXT NOT NULL,
    file_type TEXT NOT NULL, -- 'jobs_csv', 'profile_pic', 'resume_tex', 'resume_docx', 'resume_pdf'
    filename TEXT NOT NULL,
    content BYTEA,
    mime_type TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, file_type)
);

-- Table for storing resume generation cache
CREATE TABLE IF NOT EXISTS resume_generation_cache (
    user_id TEXT NOT NULL,
    cache_key TEXT NOT NULL,
    data JSONB NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, cache_key)
);
