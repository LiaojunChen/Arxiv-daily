export interface AuthorAffiliation {
  author: string;
  affiliation: string;
}

export interface Paper {
  arxiv_id: string;
  title: string;
  authors: string[];
  affiliations: AuthorAffiliation[];
  abstract: string;
  categories: string[];
  published: string;
  pdf_url: string;
  abstract_url: string;
  similarity_score?: number;
  matched_by?: string;
  hf_upvotes?: number;
  source: "zotero_similar" | "followed" | "huggingface";
}

export interface PapersData {
  date: string;
  updated_at: string;
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
}

export interface ChatMessage {
  role: "user" | "assistant" | "system";
  content: string;
}
