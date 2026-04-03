const VENUE_ABBREV: Record<string, string> = {
  // CCF-A Conferences
  "aaai conference on artificial intelligence": "AAAI",
  "neural information processing systems": "NeurIPS",
  "advances in neural information processing systems": "NeurIPS",
  "neurips": "NeurIPS",
  "neurips 2025": "NeurIPS 2025",
  "international conference on machine learning": "ICML",
  "international joint conference on artificial intelligence": "IJCAI",
  "annual meeting of the association for computational linguistics": "ACL",
  "meeting of the association for computational linguistics": "ACL",
  "ieee/cvf conference on computer vision and pattern recognition": "CVPR",
  "computer vision and pattern recognition": "CVPR",
  "ieee conference on computer vision and pattern recognition": "CVPR",
  "ieee/cvf international conference on computer vision": "ICCV",
  "international conference on computer vision": "ICCV",
  "european conference on computer vision": "ECCV",
  "acm international conference on multimedia": "ACM MM",
  "acm sigcomm conference": "SIGCOMM",
  "acm sigmod international conference on management of data": "SIGMOD",
  "international conference on very large data bases": "VLDB",
  "proceedings of the vldb endowment": "VLDB",
  "ieee international conference on data engineering": "ICDE",
  "acm symposium on theory of computing": "STOC",
  "symposium on theory of computing": "STOC",
  "ieee annual symposium on foundations of computer science": "FOCS",
  "acm conference on computer and communications security": "CCS",
  "acm sigsac conference on computer and communications security": "CCS",
  "ieee symposium on security and privacy": "IEEE S&P",
  "usenix security symposium": "USENIX Security",
  "international conference on software engineering": "ICSE",
  "acm conference on human factors in computing systems": "CHI",
  "conference on human factors in computing systems": "CHI",
  "acm sigir conference on research and development in information retrieval": "SIGIR",
  "international acm sigir conference": "SIGIR",
  "the web conference": "WWW",
  "world wide web conference": "WWW",
  "acm sigkdd international conference on knowledge discovery and data mining": "KDD",
  "knowledge discovery and data mining": "KDD",
  "usenix symposium on operating systems design and implementation": "OSDI",
  "acm symposium on operating systems principles": "SOSP",
  "international symposium on computer architecture": "ISCA",
  "architectural support for programming languages and operating systems": "ASPLOS",
  "acm sigplan conference on programming language design and implementation": "PLDI",
  "robotics: science and systems": "RSS",

  // CCF-A NLP
  "empirical methods in natural language processing": "EMNLP",
  "conference on empirical methods in natural language processing": "EMNLP",
  "north american chapter of the association for computational linguistics": "NAACL",
  "annual conference of the north american chapter of the association for computational linguistics": "NAACL",

  // CCF-B Conferences
  "conference on learning theory": "COLT",
  "international conference on artificial intelligence and statistics": "AISTATS",
  "conference on uncertainty in artificial intelligence": "UAI",
  "european conference on artificial intelligence": "ECAI",
  "international conference on learning representations": "ICLR",
  "international conference on computational linguistics": "COLING",
  "british machine vision conference": "BMVC",
  "ieee/cvf winter conference on applications of computer vision": "WACV",
  "winter conference on applications of computer vision": "WACV",
  "ieee international conference on robotics and automation": "ICRA",
  "ieee/rsj international conference on intelligent robots and systems": "IROS",
  "conference on robot learning": "CoRL",
  "acm international conference on information and knowledge management": "CIKM",
  "ieee international conference on data mining": "ICDM",
  "acm international conference on web search and data mining": "WSDM",
  "european conference on information retrieval": "ECIR",
  "annual conference of the international speech communication association": "INTERSPEECH",
  "ieee international conference on acoustics, speech and signal processing": "ICASSP",
  "medical image computing and computer assisted intervention": "MICCAI",
  "international conference on medical image computing and computer-assisted intervention": "MICCAI",
  "european conference on computer systems": "EuroSys",
  "usenix annual technical conference": "USENIX ATC",
  "acm international conference on mobile computing and networking": "MobiCom",
  "network and distributed system security symposium": "NDSS",
  "ieee/acm international conference on automated software engineering": "ASE",
  "acm symposium on user interface software and technology": "UIST",
  "acm international joint conference on pervasive and ubiquitous computing": "UbiComp",
  "ieee international conference on computer communications": "INFOCOM",
  "ieee international parallel and distributed processing symposium": "IPDPS",
  "international conference for high performance computing, networking, storage and analysis": "SC",
  "conference on machine learning and systems": "MLSys",
  "design automation conference": "DAC",

  // CCF-C Conferences
  "asian conference on computer vision": "ACCV",
  "international conference on pattern recognition": "ICPR",
  "international joint conference on neural networks": "IJCNN",
  "genetic and evolutionary computation conference": "GECCO",
  "pacific-asia conference on knowledge discovery and data mining": "PAKDD",
  "international conference on language resources and evaluation": "LREC",
  "european chapter of the association for computational linguistics": "EACL",
  "conference on computational natural language learning": "CoNLL",

  // Journals (keep as-is but shorter)
  "ieee transactions on pattern analysis and machine intelligence": "TPAMI",
  "international journal of computer vision": "IJCV",
  "journal of machine learning research": "JMLR",
  "ieee transactions on image processing": "TIP",
  "ieee transactions on knowledge and data engineering": "TKDE",
  "ieee transactions on software engineering": "TSE",
  "acm transactions on graphics": "TOG",
  "ieee transactions on neural networks and learning systems": "TNNLS",
  "ieee transactions on cybernetics": "TCYB",
  "transactions of the association for computational linguistics": "TACL",
  "ieee transactions on multimedia": "TMM",
  "ieee transactions on visualization and computer graphics": "TVCG",
  "pattern recognition": "PR",
  "nature machine intelligence": "Nat. Mach. Intell.",
  "ieee transactions on medical imaging": "TMI",

  // Common non-CCF venues
  "arxiv.org": "arXiv",
  "arxiv": "arXiv",
  "biorxiv": "bioRxiv",
};

export function abbreviateVenue(venue: string, year?: number): string {
  if (!venue) return "";

  const vl = venue.toLowerCase().trim();

  // Direct match
  if (VENUE_ABBREV[vl]) {
    const abbr = VENUE_ABBREV[vl];
    const alreadyHasYear = year && abbr.endsWith(String(year));
    return year && !alreadyHasYear ? `${abbr} ${year}` : abbr;
  }

  // Try stripping year suffix: "CVPR 2024" -> "cvpr"
  const stripped = vl.replace(/\s*\d{4}\s*$/, "").trim();
  if (VENUE_ABBREV[stripped]) {
    const abbr = VENUE_ABBREV[stripped];
    const alreadyHasYear = year && abbr.endsWith(String(year));
    return year && !alreadyHasYear ? `${abbr} ${year}` : abbr;
  }

  // Try first word as abbreviation
  const firstWord = venue.split(/\s/)[0];
  if (firstWord.length <= 10 && firstWord === firstWord.toUpperCase()) {
    return year ? `${firstWord} ${year}` : firstWord;
  }

  // If venue is already short enough, return as-is (skip year if venue already ends with it)
  if (venue.length <= 20) {
    const endsWithYear = year && venue.endsWith(String(year));
    return year && !endsWithYear ? `${venue} ${year}` : venue;
  }

  // Fallback: truncate
  const endsWithYear = year && venue.endsWith(String(year));
  return year && !endsWithYear ? `${venue.slice(0, 30)}… ${year}` : `${venue.slice(0, 30)}…`;
}
