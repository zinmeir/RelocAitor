"""
Concept prototypes for semantic matching.

Each concept is described by a few plain sentences. A clause of the user's
prompt matches a concept when its sentence embedding is close to any of that
concept's prototypes (cosine similarity above a threshold tuned on the
training prompts, never on the test prompts).

These were written independently of ml/data/prompts.py TEST, so the held-out
evaluation stays honest.
"""

FACTOR_PROTOTYPES = {
    "salary": [
        "high salaries and good pay",
        "I want to earn a lot more money",
        "jobs that pay well",
        "strong earning potential and generous wages",
        "a better income than I get at home",
    ],
    "cost": [
        "a low cost of living",
        "cheap rent and affordable groceries",
        "my money should go further there",
        "an inexpensive country to live in",
        "I can't afford expensive cities",
    ],
    "pr": [
        "a path to permanent residency",
        "I want to settle there for good and eventually become a citizen",
        "long-term stability and the right to stay permanently",
        "a green card or citizenship in the future",
        "not having to renew a visa every year",
    ],
    "job": [
        "a strong job market with many openings",
        "it should be easy to find employment",
        "lots of career opportunities",
        "companies are hiring and unemployment is low",
        "good prospects for finding work in my field",
    ],
    "climate": [
        "warm, sunny weather all year",
        "a pleasant climate with mild winters",
        "I hate the cold and want more sun",
        "tropical weather and beaches",
        "lots of sunshine and blue skies",
    ],
    "safety": [
        "a safe country with low crime",
        "I want to feel secure walking around at night",
        "peaceful and politically stable",
        "a safe place to raise children",
        "no violence or danger on the streets",
    ],
    "healthcare": [
        "excellent healthcare and hospitals",
        "access to good doctors and medical treatment",
        "a strong public health system",
        "quality medical care for a chronic condition",
        "health insurance and clinics that work well",
    ],
    "english": [
        "people speak English",
        "I only speak English and don't want to learn a new language",
        "an English-speaking country",
        "it should be easy to communicate without the local language",
        "English is widely used at work and in daily life",
    ],
    "internet": [
        "fast and reliable internet",
        "good broadband for working online",
        "stable connection for video calls",
        "high-speed fibre and mobile data",
        "strong digital infrastructure and connectivity",
    ],
}

VISA_PROTOTYPES = {
    "nomad": [
        "I work remotely and can live anywhere",
        "a digital nomad visa for remote workers",
        "I'm a freelancer with clients abroad",
        "my job is online so location doesn't matter",
    ],
    "study": [
        "I want to study at a university abroad",
        "a student visa for a master's degree",
        "studying overseas and getting a degree",
        "enrolling in a college in another country",
    ],
    "passive": [
        "I'm retired and want to live abroad on my pension",
        "a retirement visa for people with passive income",
        "living off savings and investments in retirement",
        "a place to retire comfortably",
    ],
    "investor": [
        "a golden visa through investment",
        "residency by buying property",
        "investing money to get a residence permit",
        "citizenship or residency by investment",
    ],
    "startup": [
        "I want to start my own company abroad",
        "a startup visa for founders and entrepreneurs",
        "launching a business in another country",
        "self-employment and setting up a company",
    ],
    "family": [
        "joining my spouse who lives there",
        "a family reunification visa",
        "moving to be with my partner",
        "my husband or wife is a citizen there",
    ],
    "skilled": [
        "a work visa for skilled professionals",
        "I have a job offer from a company abroad",
        "an employer will sponsor my work permit",
        "moving abroad for a qualified job in my profession",
    ],
}
