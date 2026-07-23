export interface AuthorAffiliation {
  author?: string;
  affiliation?: string;
  institution?: string;
  org?: string;
}

export interface Paper {
  arxiv_id: string;
  title: string;
  authors: string[];
  affiliations: (AuthorAffiliation | string)[];
  abstract: string;
  categories: string[];
  published: string;
  pdf_url: string;
  abstract_url: string;
  similarity_score?: number;
  matched_by?: string;
  matched_keywords?: string[];
  suppressed_keywords?: string[];
  recommendation_reason?: string;
  hf_upvotes?: number;
  source: "zotero_similar" | "interest_profile" | "followed" | "huggingface";
}

export interface PapersData {
  date: string;
  updated_at: string;
  run_id?: string;
  similar_papers: Paper[];
  followed_papers: Paper[];
  hf_papers: Paper[];
}

export interface AppSettings {
  followed_authors: string[];
  followed_institutions: string[];
  ai_api_base: string;
  ai_api_key: string;
  ai_model: string;
  feedback_access_code: string;
}

export interface ChatMessage {
  role: "user" | "assistant" | "system";
  content: string;
}
