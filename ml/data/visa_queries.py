"""
Labelled queries for evaluating visa retrieval (keyword vs semantic vs hybrid).

Each query: (text, relevant visa types, optional country codes). A visa is
relevant if its type is in the set (and, when countries are given, it belongs
to one of them). Region words in a query are handled by the app's own region
filter, exactly as in production.

Most queries are deliberately phrased WITHOUT the visa's own vocabulary
("I can work from my laptop anywhere" rather than "digital nomad visa"),
because that is where keyword search fails. A few keyword-style queries are
included so the hybrid is also checked on what keyword search already does well.

NULL queries are relocation prompts that are not asking for a visa at all: a
good retriever should return nothing for them (false hits clutter the UI).

DEV is used to tune the similarity threshold; TEST is only scored.
"""

DEV = [
    ("my employer lets me work from anywhere with a laptop", {"nomad"}, None),
    ("freelance designer with clients overseas", {"nomad"}, None),
    ("location independent work permit in Europe", {"nomad"}, None),
    ("remote work visa Portugal", {"nomad"}, ["PRT"]),
    ("I'd like to do a master's degree abroad", {"study"}, None),
    ("permit for international students in Canada", {"study"}, ["CAN"]),
    ("enrol at a university in Australia", {"study"}, ["AUS"]),
    ("living off my pension in a warm country", {"passive"}, None),
    ("retirement visa in Thailand", {"passive"}, ["THA"]),
    ("I have passive income from rentals and want to move", {"passive"}, None),
    ("buy a house and get residency", {"investor"}, None),
    ("residence permit in exchange for investment in Greece", {"investor"}, ["GRC"]),
    ("golden visa", {"investor"}, None),
    ("I want to launch my own tech company overseas", {"startup"}, None),
    ("entrepreneur visa Netherlands", {"startup"}, ["NLD"]),
    ("my wife is Canadian and I want to join her", {"family"}, ["CAN"]),
    ("reunite with my spouse abroad", {"family"}, None),
    ("a company in Germany offered me a job", {"skilled"}, ["DEU"]),
    ("work permit for nurses", {"skilled"}, None),
    ("employer sponsored visa in Australia", {"skilled"}, ["AUS"]),
    ("blue card", {"skilled"}, None),
    ("H-1B", {"skilled"}, ["USA"]),
]

TEST = [
    ("I run my business online and could live anywhere", {"nomad"}, None),
    ("permit for people working for foreign companies from Asia", {"nomad"}, None),
    ("digital nomad visa Spain", {"nomad"}, ["ESP"]),
    ("going to college overseas", {"study"}, None),
    ("student visa UK", {"study"}, ["GBR"]),
    ("PhD place at a German university", {"study"}, ["DEU"]),
    ("spending my golden years by the sea", {"passive"}, None),
    ("I no longer work and have savings to live on", {"passive"}, None),
    ("residency through buying real estate", {"investor"}, None),
    ("invest half a million and move to the US", {"investor"}, ["USA"]),
    ("citizenship by investment in the Caribbean or Europe", {"investor"}, None),
    ("founding a startup in Canada", {"startup"}, ["CAN"]),
    ("self-employed founder wanting to build a company abroad", {"startup"}, None),
    ("my husband is British and I'd move to the UK", {"family"}, ["GBR"]),
    ("partner visa", {"family"}, None),
    ("software engineer with a job offer in Japan", {"skilled"}, ["JPN"]),
    ("a hospital abroad wants to hire me as a doctor", {"skilled"}, None),
    ("skilled migration Australia", {"skilled"}, ["AUS"]),
    ("express entry", {"skilled"}, ["CAN"]),
    ("work visa for an IT specialist in the Gulf", {"skilled"}, None),
]

NULL_DEV = [
    "safe and cheap with good weather",
    "somewhere with great healthcare",
    "I want high salaries and English",
    "compare Canada and Australia",
    "somewhere like Portugal but cheaper",
    "fast internet and low crime",
    "good morning",
    "top 5 countries in Europe",
]

NULL_TEST = [
    "affordable, sunny and peaceful",
    "a country with excellent hospitals",
    "good jobs and an English speaking environment",
    "anywhere but Russia or China",
    "cheap rent and nice beaches",
    "help me choose a country",
    "colder places are fine",
]
