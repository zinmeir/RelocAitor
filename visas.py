"""
visas.py — Curated visa pathway data for each country in the dataset.

Each country has a list of visa pathways. Each pathway has:
- type:         one of "skilled" / "nomad" / "investor" / "study" / "family" / "startup"
- name:         official or common visa name
- difficulty:   "Easy" | "Moderate" | "Hard"  (subjective — relative to peers)
- duration:     typical initial validity / pathway duration
- pr_route:     does this lead to PR? "Yes" | "Eventually" | "No"
- min_income:   approximate minimum monthly income in USD (or 0 if N/A)
- summary:      one-line description

Note: visa rules change frequently. This data is illustrative for a
demo / portfolio context. Always verify with official sources.
"""

# Difficulty rank for sorting/filtering
DIFFICULTY_RANK = {"Easy": 0, "Moderate": 1, "Hard": 2}


VISA_DATA = {
    # ---------------- North America ----------------
    "USA": [
        {"type": "skilled", "name": "H-1B Specialty Worker", "difficulty": "Hard",
         "duration": "3 years (renewable)", "pr_route": "Eventually", "min_income": 5000,
         "summary": "Sponsored by US employer; lottery-based with capped annual quota."},
        {"type": "investor", "name": "EB-5 Investor Green Card", "difficulty": "Moderate",
         "duration": "Direct PR", "pr_route": "Yes", "min_income": 0,
         "summary": "Invest $800K-$1.05M in qualified US enterprise creating ≥10 jobs."},
        {"type": "study", "name": "F-1 Student Visa", "difficulty": "Moderate",
         "duration": "Length of program", "pr_route": "No", "min_income": 0,
         "summary": "Full-time enrollment at SEVP-approved school; can lead to OPT work."},
    ],
    "CAN": [
        {"type": "skilled", "name": "Express Entry (FSW)", "difficulty": "Moderate",
         "duration": "Direct PR", "pr_route": "Yes", "min_income": 0,
         "summary": "Points-based PR for skilled workers; ~6-month average processing."},
        {"type": "startup", "name": "Start-up Visa Program", "difficulty": "Moderate",
         "duration": "Direct PR", "pr_route": "Yes", "min_income": 0,
         "summary": "Get backing from designated VC/incubator for innovative business."},
        {"type": "study", "name": "Study Permit + PGWP", "difficulty": "Easy",
         "duration": "Up to 3 years post-graduation", "pr_route": "Eventually", "min_income": 0,
         "summary": "Study + work afterwards; strong stepping-stone to PR via CEC."},
    ],
    "MEX": [
        {"type": "nomad", "name": "Temporary Resident Visa", "difficulty": "Easy",
         "duration": "1-4 years", "pr_route": "Eventually", "min_income": 2600,
         "summary": "Show monthly income or savings; renewable up to 4 years then PR."},
        {"type": "investor", "name": "Investor Resident Visa", "difficulty": "Moderate",
         "duration": "1-4 years", "pr_route": "Eventually", "min_income": 0,
         "summary": "Invest ~$220K in Mexican business or property."},
    ],
    "CRI": [
        {"type": "nomad", "name": "Rentista / Digital Nomad", "difficulty": "Easy",
         "duration": "1-2 years (renewable)", "pr_route": "Eventually", "min_income": 3000,
         "summary": "Show stable foreign income; renewable, leads to PR after 3 years."},
        {"type": "investor", "name": "Inversionista", "difficulty": "Easy",
         "duration": "2 years renewable", "pr_route": "Eventually", "min_income": 0,
         "summary": "Invest $150K+ in business, real estate, or government bonds."},
    ],
    "PAN": [
        {"type": "investor", "name": "Friendly Nations Visa", "difficulty": "Easy",
         "duration": "Direct PR", "pr_route": "Yes", "min_income": 0,
         "summary": "Citizens of 50+ countries can get PR via business or property."},
        {"type": "nomad", "name": "Short-Stay Remote Worker", "difficulty": "Easy",
         "duration": "9 months", "pr_route": "No", "min_income": 3000,
         "summary": "Quick remote-worker visa; no path to PR but easy entry."},
    ],

    # ---------------- South America ----------------
    "BRA": [
        {"type": "nomad", "name": "Digital Nomad Visa", "difficulty": "Easy",
         "duration": "1 year (renewable +1)", "pr_route": "No", "min_income": 1500,
         "summary": "Remote work for foreign employer; quick approval."},
        {"type": "investor", "name": "Investor Visa (VIPER)", "difficulty": "Moderate",
         "duration": "2 years to PR", "pr_route": "Yes", "min_income": 0,
         "summary": "Invest BRL 500K+ in business or BRL 1M+ in real estate."},
    ],
    "ARG": [
        {"type": "nomad", "name": "Digital Nomad Visa", "difficulty": "Easy",
         "duration": "6 months (renewable)", "pr_route": "No", "min_income": 0,
         "summary": "Open to remote workers; very low income threshold."},
        {"type": "skilled", "name": "Rentista Visa", "difficulty": "Easy",
         "duration": "1 year renewable", "pr_route": "Eventually", "min_income": 2500,
         "summary": "Show stable monthly income; PR after 2-3 years."},
    ],
    "CHL": [
        {"type": "skilled", "name": "Temporary Resident Visa", "difficulty": "Moderate",
         "duration": "1 year (renewable)", "pr_route": "Eventually", "min_income": 0,
         "summary": "Multiple pathways: work contract, professional services, retiree."},
    ],
    "URY": [
        {"type": "skilled", "name": "Permanent Residency", "difficulty": "Easy",
         "duration": "Direct PR", "pr_route": "Yes", "min_income": 1500,
         "summary": "Show stable income; one of South America's easiest PR routes."},
    ],
    "COL": [
        {"type": "nomad", "name": "Digital Nomad Visa (V Type)", "difficulty": "Easy",
         "duration": "Up to 2 years", "pr_route": "No", "min_income": 900,
         "summary": "Very low income threshold; remote workers welcome."},
        {"type": "investor", "name": "M Visa - Investment", "difficulty": "Moderate",
         "duration": "3 years renewable", "pr_route": "Eventually", "min_income": 0,
         "summary": "Invest ~$30K in property or $115K in a business."},
    ],
    "PER": [
        {"type": "nomad", "name": "Rentista Visa", "difficulty": "Easy",
         "duration": "1 year renewable", "pr_route": "Eventually", "min_income": 1000,
         "summary": "Show stable income; renewable indefinitely."},
    ],

    # ---------------- Europe ----------------
    "GBR": [
        {"type": "skilled", "name": "Skilled Worker Visa", "difficulty": "Moderate",
         "duration": "Up to 5 years", "pr_route": "Eventually", "min_income": 3500,
         "summary": "Job offer from licensed sponsor; salary thresholds apply."},
        {"type": "investor", "name": "Innovator Founder Visa", "difficulty": "Hard",
         "duration": "3 years initial", "pr_route": "Eventually", "min_income": 0,
         "summary": "Endorsed innovative business idea; replaces old Tier 1."},
        {"type": "study", "name": "Student Visa + Graduate Route", "difficulty": "Easy",
         "duration": "Study + 2-3 years post-grad work", "pr_route": "Eventually", "min_income": 0,
         "summary": "Strong post-study work rights; PSW visa for grads."},
    ],
    "IRL": [
        {"type": "skilled", "name": "Critical Skills Employment Permit", "difficulty": "Moderate",
         "duration": "2 years renewable", "pr_route": "Eventually", "min_income": 3500,
         "summary": "Fast-track for tech, engineering, healthcare professionals."},
        {"type": "study", "name": "Stamp 2 + Third-Level Graduate Scheme", "difficulty": "Easy",
         "duration": "Study + up to 2 years post-grad", "pr_route": "Eventually", "min_income": 0,
         "summary": "Generous post-study work rights for graduates."},
    ],
    "DEU": [
        {"type": "skilled", "name": "EU Blue Card", "difficulty": "Moderate",
         "duration": "4 years", "pr_route": "Eventually", "min_income": 4500,
         "summary": "Tech/engineering jobs paying ~€45K+; PR after 21-33 months."},
        {"type": "skilled", "name": "Job Seeker Visa", "difficulty": "Easy",
         "duration": "6 months", "pr_route": "No directly", "min_income": 0,
         "summary": "Come search for a job; convert to work permit if successful."},
        {"type": "study", "name": "Student Visa + 18-Month Job Search", "difficulty": "Easy",
         "duration": "Study + 18 months", "pr_route": "Eventually", "min_income": 0,
         "summary": "Free or low-cost universities; strong post-grad pathway."},
    ],
    "FRA": [
        {"type": "skilled", "name": "Talent Passport", "difficulty": "Moderate",
         "duration": "4 years renewable", "pr_route": "Eventually", "min_income": 3000,
         "summary": "Multiple categories: skilled, researcher, founder, artist."},
        {"type": "study", "name": "Long-Stay Student Visa", "difficulty": "Easy",
         "duration": "1 year renewable", "pr_route": "Eventually", "min_income": 0,
         "summary": "Affordable tuition; APS card gives 1 year to find work after."},
    ],
    "NLD": [
        {"type": "skilled", "name": "Highly Skilled Migrant Visa", "difficulty": "Moderate",
         "duration": "5 years", "pr_route": "Eventually", "min_income": 4500,
         "summary": "Recognized sponsor required; 30% tax ruling for newcomers."},
        {"type": "startup", "name": "DAFT (US treaty)", "difficulty": "Easy",
         "duration": "2 years renewable", "pr_route": "Eventually", "min_income": 0,
         "summary": "US citizens: deposit €4,500 in a Dutch business."},
        {"type": "startup", "name": "Startup Visa", "difficulty": "Moderate",
         "duration": "1 year (then self-employed)", "pr_route": "Eventually", "min_income": 0,
         "summary": "Work with a recognized facilitator on innovative venture."},
    ],
    "BEL": [
        {"type": "skilled", "name": "Single Permit (Work + Residence)", "difficulty": "Moderate",
         "duration": "Up to 3 years", "pr_route": "Eventually", "min_income": 3500,
         "summary": "Combined work and residence permit via employer sponsor."},
    ],
    "SWE": [
        {"type": "skilled", "name": "Work Permit", "difficulty": "Easy",
         "duration": "Up to 2 years", "pr_route": "Eventually", "min_income": 2800,
         "summary": "Job offer required; PR possible after 4 years."},
    ],
    "NOR": [
        {"type": "skilled", "name": "Skilled Worker Permit", "difficulty": "Moderate",
         "duration": "Up to 3 years", "pr_route": "Eventually", "min_income": 4500,
         "summary": "Requires education + job offer; PR after 3 years."},
    ],
    "DNK": [
        {"type": "skilled", "name": "Pay Limit Scheme", "difficulty": "Moderate",
         "duration": "Up to 4 years", "pr_route": "Eventually", "min_income": 6500,
         "summary": "High salary threshold; fast-track for top earners."},
        {"type": "skilled", "name": "Positive List Scheme", "difficulty": "Moderate",
         "duration": "Up to 4 years", "pr_route": "Eventually", "min_income": 0,
         "summary": "For occupations facing labor shortage in Denmark."},
    ],
    "FIN": [
        {"type": "skilled", "name": "Specialist Residence Permit", "difficulty": "Moderate",
         "duration": "Up to 2 years", "pr_route": "Eventually", "min_income": 3000,
         "summary": "Express-track for IT specialists, ~14-day processing."},
        {"type": "startup", "name": "Startup Permit", "difficulty": "Moderate",
         "duration": "2 years", "pr_route": "Eventually", "min_income": 0,
         "summary": "Business Finland evaluation required; innovation focus."},
    ],
    "ISL": [
        {"type": "nomad", "name": "Long-Term Remote Work Visa", "difficulty": "Easy",
         "duration": "180 days", "pr_route": "No", "min_income": 7000,
         "summary": "High income required; short-term only."},
    ],
    "CHE": [
        {"type": "skilled", "name": "B Permit (Work)", "difficulty": "Hard",
         "duration": "5 years", "pr_route": "Eventually", "min_income": 6500,
         "summary": "Strict quotas; easier for EU/EFTA citizens. PR after 10 years."},
    ],
    "AUT": [
        {"type": "skilled", "name": "Red-White-Red Card", "difficulty": "Moderate",
         "duration": "2 years", "pr_route": "Eventually", "min_income": 3200,
         "summary": "Points-based for highly qualified workers and shortage occupations."},
    ],
    "ESP": [
        {"type": "nomad", "name": "Digital Nomad Visa", "difficulty": "Easy",
         "duration": "1 year (renewable to 5)", "pr_route": "Eventually", "min_income": 2700,
         "summary": "Remote work for foreign employers; flat 24% tax option."},
        {"type": "investor", "name": "Non-Lucrative Visa", "difficulty": "Easy",
         "duration": "1 year renewable", "pr_route": "Eventually", "min_income": 2900,
         "summary": "Show passive income or savings; can't work locally but PR-eligible."},
    ],
    "PRT": [
        {"type": "nomad", "name": "D8 Digital Nomad Visa", "difficulty": "Easy",
         "duration": "1 year (renewable to 5)", "pr_route": "Eventually", "min_income": 3500,
         "summary": "Best-in-class for remote workers; PR after 5 years."},
        {"type": "investor", "name": "D7 Passive Income Visa", "difficulty": "Easy",
         "duration": "2 years renewable", "pr_route": "Eventually", "min_income": 900,
         "summary": "Show stable passive income (rental, pension, dividends)."},
    ],
    "ITA": [
        {"type": "nomad", "name": "Digital Nomad Visa", "difficulty": "Moderate",
         "duration": "1 year renewable", "pr_route": "Eventually", "min_income": 2700,
         "summary": "Launched 2024; for highly skilled remote workers."},
        {"type": "investor", "name": "Investor Visa", "difficulty": "Moderate",
         "duration": "2 years renewable", "pr_route": "Eventually", "min_income": 0,
         "summary": "€250K-2M into Italian companies, bonds, or philanthropy."},
    ],
    "GRC": [
        {"type": "investor", "name": "Golden Visa", "difficulty": "Easy",
         "duration": "5 years renewable", "pr_route": "Yes", "min_income": 0,
         "summary": "€250K+ real estate investment grants residence (no stay required)."},
        {"type": "nomad", "name": "Digital Nomad Visa", "difficulty": "Easy",
         "duration": "1 year renewable", "pr_route": "Eventually", "min_income": 3500,
         "summary": "50% tax break for first 7 years for remote workers."},
    ],
    "CZE": [
        {"type": "skilled", "name": "Employee Card", "difficulty": "Moderate",
         "duration": "2 years renewable", "pr_route": "Eventually", "min_income": 1500,
         "summary": "Job offer + qualifications; PR after 5 years."},
        {"type": "nomad", "name": "Zivno (Trade License)", "difficulty": "Easy",
         "duration": "2 years renewable", "pr_route": "Eventually", "min_income": 0,
         "summary": "Self-employment route for freelancers/digital nomads."},
    ],
    "POL": [
        {"type": "skilled", "name": "Type A Work Permit", "difficulty": "Easy",
         "duration": "Up to 3 years", "pr_route": "Eventually", "min_income": 1200,
         "summary": "Employer-sponsored; relatively quick process."},
    ],
    "HUN": [
        {"type": "investor", "name": "Guest Investor Program", "difficulty": "Moderate",
         "duration": "10 years", "pr_route": "Yes", "min_income": 0,
         "summary": "€250K real estate fund or €1M property; long-term residence."},
    ],
    "EST": [
        {"type": "nomad", "name": "Digital Nomad Visa", "difficulty": "Easy",
         "duration": "1 year", "pr_route": "No", "min_income": 4500,
         "summary": "Pioneered the digital nomad visa concept; 100% online process."},
        {"type": "startup", "name": "e-Residency + Startup Visa", "difficulty": "Easy",
         "duration": "Up to 5 years", "pr_route": "Eventually", "min_income": 0,
         "summary": "Run an EU company remotely or relocate via startup visa."},
    ],
    "ROU": [
        {"type": "nomad", "name": "Digital Nomad Visa", "difficulty": "Easy",
         "duration": "1 year renewable", "pr_route": "No", "min_income": 3700,
         "summary": "Tax-friendly for remote workers; low cost of living."},
    ],
    "HRV": [
        {"type": "nomad", "name": "Digital Nomad Visa", "difficulty": "Easy",
         "duration": "1 year (no renewal)", "pr_route": "No", "min_income": 2500,
         "summary": "One-year stay; tax-exempt on foreign income."},
    ],
    "SVN": [
        {"type": "skilled", "name": "Single Permit", "difficulty": "Moderate",
         "duration": "Up to 2 years", "pr_route": "Eventually", "min_income": 1700,
         "summary": "Combined work and residence permit; EU labor market test applies."},
    ],

    # ---------------- Oceania ----------------
    "AUS": [
        {"type": "skilled", "name": "Skilled Independent Visa (189)", "difficulty": "Moderate",
         "duration": "Direct PR", "pr_route": "Yes", "min_income": 0,
         "summary": "Points-based PR; no sponsor needed if you score high enough."},
        {"type": "skilled", "name": "Employer-Sponsored (482/186)", "difficulty": "Moderate",
         "duration": "2-4 years (then PR)", "pr_route": "Eventually", "min_income": 4500,
         "summary": "Sponsored by Australian employer; PR via 186 transition."},
        {"type": "study", "name": "Subclass 500 + Post-Study Work", "difficulty": "Easy",
         "duration": "Study + 2-6 years post-grad", "pr_route": "Eventually", "min_income": 0,
         "summary": "Post-study work visa lengths vary by location and qualification."},
    ],
    "NZL": [
        {"type": "skilled", "name": "Skilled Migrant Category", "difficulty": "Moderate",
         "duration": "Direct PR", "pr_route": "Yes", "min_income": 0,
         "summary": "Points-based PR; favors job offer + in-demand skills."},
        {"type": "skilled", "name": "Accredited Employer Work Visa", "difficulty": "Moderate",
         "duration": "Up to 3 years", "pr_route": "Eventually", "min_income": 3500,
         "summary": "Employer accreditation simplifies the process."},
    ],

    # ---------------- Asia ----------------
    "JPN": [
        {"type": "skilled", "name": "Highly Skilled Professional", "difficulty": "Moderate",
         "duration": "5 years", "pr_route": "Eventually", "min_income": 3500,
         "summary": "Points-based; PR possible in 1-3 years for high scorers."},
        {"type": "nomad", "name": "Digital Nomad Visa", "difficulty": "Easy",
         "duration": "6 months (no renewal)", "pr_route": "No", "min_income": 8400,
         "summary": "Launched 2024; high income bar, short stay."},
        {"type": "study", "name": "Student Visa + Job Hunting", "difficulty": "Easy",
         "duration": "Study + up to 1 year", "pr_route": "Eventually", "min_income": 0,
         "summary": "Strong pipeline into Japanese employment after graduation."},
    ],
    "KOR": [
        {"type": "skilled", "name": "E-7 Specialty Occupation", "difficulty": "Moderate",
         "duration": "1-3 years", "pr_route": "Eventually", "min_income": 2500,
         "summary": "Job offer required; for skilled professionals."},
        {"type": "nomad", "name": "Workation Visa (F-1-D)", "difficulty": "Easy",
         "duration": "1 year (+1 renewal)", "pr_route": "No", "min_income": 6700,
         "summary": "Launched 2024 for remote workers; high income bar."},
    ],
    "SGP": [
        {"type": "skilled", "name": "Employment Pass", "difficulty": "Hard",
         "duration": "Up to 2 years", "pr_route": "Eventually", "min_income": 4000,
         "summary": "Min S$5,000/mo (S$10,500 for finance); points-based COMPASS scoring."},
        {"type": "skilled", "name": "Tech.Pass", "difficulty": "Hard",
         "duration": "2 years", "pr_route": "Eventually", "min_income": 17000,
         "summary": "For top-tier tech founders/leaders; min S$22,500/mo income."},
        {"type": "skilled", "name": "ONE Pass (Top Talent)", "difficulty": "Hard",
         "duration": "5 years", "pr_route": "Eventually", "min_income": 23000,
         "summary": "For exceptional individuals: min S$30K/mo or top-tier achievement."},
    ],
    "TWN": [
        {"type": "skilled", "name": "Employment Gold Card", "difficulty": "Moderate",
         "duration": "1-3 years", "pr_route": "Eventually", "min_income": 5400,
         "summary": "All-in-one work + residence + reentry permit for talents."},
    ],
    "HKG": [
        {"type": "skilled", "name": "General Employment Policy", "difficulty": "Moderate",
         "duration": "2-3 years", "pr_route": "Eventually", "min_income": 3000,
         "summary": "Employer sponsorship; PR after 7 years of continuous residence."},
        {"type": "skilled", "name": "Top Talent Pass Scheme", "difficulty": "Easy",
         "duration": "2 years", "pr_route": "Eventually", "min_income": 0,
         "summary": "For grads of top universities; income or alma mater-based."},
    ],
    "CHN": [
        {"type": "skilled", "name": "Z Visa (Work Permit)", "difficulty": "Hard",
         "duration": "1-5 years", "pr_route": "Eventually", "min_income": 3000,
         "summary": "Job offer + qualifications; tier system A/B/C."},
    ],
    "VNM": [
        {"type": "skilled", "name": "Work Permit", "difficulty": "Moderate",
         "duration": "Up to 2 years", "pr_route": "No directly", "min_income": 0,
         "summary": "Employer-sponsored; renewable; common for English teachers/tech."},
    ],
    "IND": [
        {"type": "skilled", "name": "Employment Visa", "difficulty": "Moderate",
         "duration": "Up to 5 years", "pr_route": "No directly", "min_income": 2100,
         "summary": "Min $25K/year salary; for skilled foreign professionals."},
    ],
    "IDN": [
        {"type": "nomad", "name": "Second Home Visa (E33G)", "difficulty": "Moderate",
         "duration": "5-10 years", "pr_route": "No directly", "min_income": 0,
         "summary": "Deposit ~$130K in Indonesian bank; long-stay option."},
        {"type": "nomad", "name": "B211A Remote Worker", "difficulty": "Easy",
         "duration": "60 days (extendable to 180)", "pr_route": "No", "min_income": 2000,
         "summary": "Common for Bali nomads; short-term but easy."},
    ],
    "PHL": [
        {"type": "investor", "name": "SRRV (Special Resident Retiree)", "difficulty": "Easy",
         "duration": "Indefinite", "pr_route": "Yes", "min_income": 0,
         "summary": "Deposit $10K-50K (varies by age); permanent residence."},
    ],
    "MYS": [
        {"type": "investor", "name": "MM2H (Malaysia My 2nd Home)", "difficulty": "Moderate",
         "duration": "5-20 years", "pr_route": "No directly", "min_income": 0,
         "summary": "Deposit + monthly income proof; long-term renewable visa."},
        {"type": "nomad", "name": "DE Rantau Nomad Pass", "difficulty": "Easy",
         "duration": "1 year (renewable +1)", "pr_route": "No", "min_income": 2000,
         "summary": "Designed for tech remote workers; quick processing."},
    ],
    "THA": [
        {"type": "nomad", "name": "Long-Term Resident Visa (LTR)", "difficulty": "Moderate",
         "duration": "10 years", "pr_route": "No directly", "min_income": 6700,
         "summary": "For wealthy globals, retirees, professionals; tax incentives."},
        {"type": "nomad", "name": "Destination Thailand Visa (DTV)", "difficulty": "Easy",
         "duration": "5 years (180 days/visit)", "pr_route": "No", "min_income": 0,
         "summary": "Launched 2024; for nomads, soft-power activities; no income req."},
    ],
    "LKA": [
        {"type": "investor", "name": "My Dream Home Visa", "difficulty": "Easy",
         "duration": "5-10 years", "pr_route": "No", "min_income": 0,
         "summary": "$75K deposit grants long-term residence."},
    ],

    # ---------------- Middle East ----------------
    "ARE": [
        {"type": "skilled", "name": "Standard Work Visa", "difficulty": "Easy",
         "duration": "2 years", "pr_route": "No", "min_income": 1100,
         "summary": "Employer-sponsored; very common, fast process."},
        {"type": "investor", "name": "Golden Visa (10-year)", "difficulty": "Moderate",
         "duration": "10 years renewable", "pr_route": "No", "min_income": 8200,
         "summary": "AED 2M property, business, or talent track; family included."},
        {"type": "nomad", "name": "Virtual Work Residence", "difficulty": "Easy",
         "duration": "1 year renewable", "pr_route": "No", "min_income": 3500,
         "summary": "Dubai's remote worker visa; tax-free local income."},
    ],
    "QAT": [
        {"type": "skilled", "name": "Work Visa", "difficulty": "Easy",
         "duration": "Up to 5 years", "pr_route": "No directly", "min_income": 1500,
         "summary": "Sponsored by Qatari employer; tax-free salaries."},
    ],
    "SAU": [
        {"type": "skilled", "name": "Work Visa (Iqama)", "difficulty": "Easy",
         "duration": "1-2 years renewable", "pr_route": "No directly", "min_income": 1300,
         "summary": "Employer sponsorship required; major reform of system in progress."},
        {"type": "investor", "name": "Premium Residency", "difficulty": "Moderate",
         "duration": "1 year or permanent", "pr_route": "Yes", "min_income": 0,
         "summary": "Pay flat fee or invest; family included, no sponsor needed."},
    ],
    "ISR": [
        {"type": "skilled", "name": "B/1 Work Visa", "difficulty": "Hard",
         "duration": "1 year renewable", "pr_route": "No directly", "min_income": 0,
         "summary": "Strict process; mostly for tech and academic specialists."},
    ],
    "TUR": [
        {"type": "investor", "name": "Citizenship by Investment", "difficulty": "Easy",
         "duration": "Direct citizenship", "pr_route": "Yes", "min_income": 0,
         "summary": "$400K real estate or $500K investment → Turkish passport."},
        {"type": "nomad", "name": "Digital Nomad Visa", "difficulty": "Easy",
         "duration": "1 year", "pr_route": "No", "min_income": 3000,
         "summary": "Launched 2024; for remote workers under age 55."},
    ],
    "BHR": [
        {"type": "investor", "name": "Golden Residency", "difficulty": "Moderate",
         "duration": "10 years renewable", "pr_route": "No", "min_income": 5300,
         "summary": "Property, talent, or pension-based; family included."},
    ],

    # ---------------- Africa ----------------
    "ZAF": [
        {"type": "skilled", "name": "Critical Skills Visa", "difficulty": "Moderate",
         "duration": "Up to 5 years", "pr_route": "Eventually", "min_income": 0,
         "summary": "For occupations on the critical skills list; PR after 5 years."},
        {"type": "nomad", "name": "Remote Work Visa", "difficulty": "Easy",
         "duration": "1 year (extendable)", "pr_route": "No", "min_income": 2900,
         "summary": "Launched 2024; for remote workers earning min ZAR 1M/year."},
    ],
    "EGY": [
        {"type": "skilled", "name": "Work Permit", "difficulty": "Moderate",
         "duration": "1 year renewable", "pr_route": "No directly", "min_income": 0,
         "summary": "Employer-sponsored; foreign worker quotas apply."},
    ],
    "MAR": [
        {"type": "skilled", "name": "Carte de Séjour", "difficulty": "Moderate",
         "duration": "1-10 years", "pr_route": "Eventually", "min_income": 0,
         "summary": "Multiple sub-categories: work, family, retirement."},
    ],
    "KEN": [
        {"type": "investor", "name": "Class G Investor Permit", "difficulty": "Moderate",
         "duration": "2 years renewable", "pr_route": "Eventually", "min_income": 0,
         "summary": "Min $100K investment in Kenyan business."},
    ],
    "NGA": [
        {"type": "skilled", "name": "Subject to Regularization (STR)", "difficulty": "Moderate",
         "duration": "2 years renewable", "pr_route": "No directly", "min_income": 0,
         "summary": "Employer-sponsored work permit."},
    ],
    "GHA": [
        {"type": "skilled", "name": "Work + Residence Permit", "difficulty": "Easy",
         "duration": "1-4 years", "pr_route": "Eventually", "min_income": 0,
         "summary": "Job offer required; relatively straightforward process."},
    ],
    "MUS": [
        {"type": "nomad", "name": "Premium Travel Visa", "difficulty": "Easy",
         "duration": "1 year renewable", "pr_route": "No", "min_income": 1500,
         "summary": "Tropical island living for remote workers."},
        {"type": "investor", "name": "Occupation Permit", "difficulty": "Easy",
         "duration": "10 years", "pr_route": "Eventually", "min_income": 3000,
         "summary": "Investor / professional / self-employed routes."},
    ],

    # ---------------- Other Europe ----------------
    "RUS": [
        {"type": "skilled", "name": "Highly Qualified Specialist (HQS)", "difficulty": "Moderate",
         "duration": "3 years", "pr_route": "Eventually", "min_income": 2500,
         "summary": "For specialists earning min RUB 167K/month."},
    ],
    "GEO": [
        {"type": "nomad", "name": "Remotely from Georgia", "difficulty": "Easy",
         "duration": "1 year (visa-free 365 days)", "pr_route": "No", "min_income": 2000,
         "summary": "Most passports get 365 visa-free days; very nomad-friendly."},
    ],
    "CYP": [
        {"type": "investor", "name": "Permanent Residency by Investment", "difficulty": "Easy",
         "duration": "Permanent", "pr_route": "Yes", "min_income": 2900,
         "summary": "€300K property + income; one of EU's faster routes."},
        {"type": "nomad", "name": "Digital Nomad Visa", "difficulty": "Easy",
         "duration": "1 year (renewable +2)", "pr_route": "No", "min_income": 3500,
         "summary": "Quick process; capped at 500/year applicants."},
    ],
}


def get_visas_for(country_code: str) -> list:
    """Return list of visa pathways for a given ISO-3 country code."""
    return VISA_DATA.get(country_code, [])


def filter_visas(visas: list, visa_type: str = None, max_difficulty: str = None) -> list:
    """Optionally filter visas by type and/or max difficulty."""
    out = visas
    if visa_type and visa_type != "any":
        out = [v for v in out if v["type"] == visa_type]
    if max_difficulty:
        max_rank = DIFFICULTY_RANK.get(max_difficulty, 2)
        out = [v for v in out if DIFFICULTY_RANK.get(v["difficulty"], 2) <= max_rank]
    return out


def all_visa_types() -> list:
    """All visa type categories present in the data."""
    return ["skilled", "nomad", "investor", "study", "family", "startup"]
