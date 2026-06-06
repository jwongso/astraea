"""Statute routing table for NZ residential tenancy law (RTA 1986).

Maps common tenant/landlord question types to the RTA sections that vector
search frequently misses. Sections are prepended to vector results so the LLM
always sees the correct legislative grounding.
"""

from core.routing import StatuteRoute

ROUTES: list[StatuteRoute] = [
    StatuteRoute(
        intent="wear_and_tear",
        include_any=(
            "fair wear and tear", "wear and tear", "normal wear",
            "tenant damage", "damage claim", "repair cost",
            "landlord charge", "liable for damage", "damage to the",
            "worn", "deteriorated", "deterioration",
            "carpet damage", "carpet replacement", "carpet clean", "carpet wear",
            "bond deduction", "deducting from", "deduct from bond",
            "withholding my bond", "withheld my bond", "withhold my bond",
            "insurance excess", "carpet stain", "stain on carpet",
            "marks on carpet", "paint mark", "paint patch",
            "crack", "cracked", "broken mirror",
            "clean on move out", "how clean for move out", "cleanliness at end",
            "vacating",
            "dented", "dent in", "accidental damage", "accident damage",
            "threadbare", "thread bare", "worn out carpet", "worn carpet",
            "garden tools", "tools left", "left tools",
            "clean and tidy", "rubbish left behind", "left rubbish", "rubbish we left",
            "wind damage", "storm damage", "hinge broke", "hinge broken",
            "before i exit", "before i move out", "before we move out",
            "meth test", "meth testing", "contamination test", "contamination",
            "withhold the quote", "withheld the quote", "won't provide quote",
            "quote for repairs", "see the quote", "quote withheld", "provide the quote",
            "replace the carpet", "replace carpet", "full carpet replacement", "new carpet",
            "breach notice", "breached for", "issued a breach", "breach of tenancy notice",
            "lawn clippings", "lawn maintenance", "lawn mowing", "mowing the lawn",
            "pin hole", "pin holes", "wallpaper damage", "wallpaper torn", "wall holes",
            "blu-tack damage", "blue tack damage", "picture holes",
            "s49a", "s49b",
        ),
        forced_sections=("NZLEG/RTA/s49A", "NZLEG/RTA/s49B", "NZLEG/RTA/s40"),
        synthetic_query=(
            "tenant not liable fair wear tear exception section 49A damage "
            "landlord cannot charge deterioration reasonable use natural forces "
            "residential tenancies act"
        ),
        notes="Tenant damage liability and fair wear and tear exception.",
    ),
    StatuteRoute(
        intent="property_change",
        include_any=(),  # unused - two-tier mode active
        include_any_precise=(
            "alteration", "alter", "altered",
            "minor change",
            "renovate", "renovation",
            "without consent", "without permission",
            "landlord consent", "written consent", "written permission",
            "landlord permission",
            "planted trees", "planted a tree", "planted several",
            "plant trees", "plant a tree",
            "drawing pin", "drawing pins", "command strip", "command strips",
            "picture hook", "picture hooks", "blu-tack", "blu tack", "bluetack",
            "security camera", "surveillance camera", "cctv",
            "doorbell camera", "camera outside", "camera facing",
            "adhesive", "renter friendly", "renter-friendly",
            "anchor furniture", "anchoring furniture", "bolt furniture",
            "bolt to wall", "fix to wall", "furniture to wall", "furniture anchoring",
        ),
        include_any_broad=(
            "plant", "planted", "tree", "trees", "shrub", "hedge",
            "garden", "backyard", "back yard", "lawn",
            "fence",
            "fixture",
            "install", "installed",
            "improvement",
        ),
        require_context_any=(
            "consent", "permission",
            "without consent", "without permission",
            "landlord consent", "landlord's consent",
            "written consent", "written permission",
            "landlord permission", "landlord's permission",
            "alteration", "minor change", "improvement",
        ),
        exclude_any=(
            "healthy homes", "building code", "building act",
            "resource management act",
            "plumbing", "sewage", "shower drain",
            "landlord failed to maintain", "landlord hasn't maintained",
            "landlord has not maintained",
            "not repaired", "not fixed", "won't fix", "wont fix",
            "hasn't fixed", "hasnt fixed",
            "broken", "not working",
            # Prevent firing when question is about someone else entering the property.
            # "without permission" and garden broad terms trigger on homeowner intrusion.
            "entered my home", "came into my home", "already in my home",
            "was in my home", "was in my house", "was in my flat",
            "home owner", "homeowner", "property owner",
            "uninvited", "is she allowed", "is he allowed",
        ),
        forced_sections=("NZLEG/RTA/s40", "NZLEG/RTA/s42A", "NZLEG/RTA/s42B"),
        synthetic_query=(
            "tenant obligations alter improve add fixtures to land garden "
            "written consent landlord section 40 42A 42B residential tenancies act"
        ),
        leg_allow_list=("NZLEG/RTA/s40", "NZLEG/RTA/s42A", "NZLEG/RTA/s42B"),
        priority=10,
        notes="Tenant changes to premises, garden, land, fixtures.",
    ),
    StatuteRoute(
        intent="repairs_maintenance",
        include_any=(
            "not working", "broken", "won't fix", "wont fix",
            "hasn't fixed", "hasnt fixed", "not fixed", "not repaired",
            "not maintained", "hasn't maintained", "has not maintained",
            "repair request", "maintenance",
            "hot water", "no hot water", "heating", "no heating",
            "mould", "mold", "damp", "dampness", "moisture", "mildew",
            "condensation", "water damage", "humid", "fungal",
            "leak", "leaking", "dripping",
            "weathertight", "habitable", "uninhabitable",
            "appliance", "oven", "stove", "fridge",
            "landlord obligation", "landlord's obligation",
            "s45",
            "pest", "pests", "pest control", "infestation", "infested",
            "spider", "spiders", "rat", "rats", "mice", "mouse",
            "cockroach", "cockroaches", "ant infestation", "fleas", "bedbugs",
            "bug", "bugs", "insect", "insects",
            "exterminator", "fumigation", "fumigated", "bitten",
            "wasp", "wasps", "wasp nest", "wasp nests", "bee", "bees", "beehive",
            "dishwasher", "washing machine", "dryer",
            "overgrown", "state of cleanliness", "clean on move in",
            "clean when i moved", "reasonably clean", "not clean", "wasn't clean",
            "wasn't cleaned", "was not cleaned", "pet hair", "undisclosed pet",
            "water tank", "tank dirty", "tank cleaning", "clean the tank",
            "flush", "flushing", "toilet flush", "flush issue",
            "heat pump", "heatpump",
            "plumbing", "blocked drain", "drain blocked", "drain issue",
            "tree roots", "roots in pipe", "roots in plumbing",
            "fallen tree", "fallen branch", "tree fallen", "branch fallen",
            "big tree", "large tree", "trees near", "tree near power",
            "vinyl flooring", "vinyl floor", "flooring coming up", "floor coming up",
            "flooring unattached", "flooring lifting", "floor lifting",
            "fence damaged", "fence damage", "fence repair", "fence broken",
            "fencing", "broken fence", "storm damage", "damage in the storm",
            "damaged in the storm", "storm damaged",
            "animal in ceiling", "possum", "something in ceiling",
            "movement in ceiling", "noise in ceiling", "creature in ceiling",
            "guttering", "gutter", "gutters", "blocked gutter",
            "drainage", "drain blocked", "puddle at", "water pooling",
            "bad smell", "horrible smell", "sewage smell", "drain smell",
            "smell from pipe", "smell from drain", "water pipe", "pipes",
            "hob", "gas hob", "oven hob", "stove hob",
            "snapped", "knob snapped", "knob broke", "knob broken",
            "tap broke", "tap broken", "tap stopped", "tap not working",
            "sliding door", "door stiff", "stiff door",
            "power disconnected", "power off", "power cut off", "reconnect power",
            "electricity disconnected", "power has been disconnected",
            "faulty wiring", "faulty circuit", "electrical fault",
            "fire hazard", "fire risk", "almost caught fire",
            "bathroom blocked", "bathroom is blocked", "toilet blocked", "sink blocked",
            "shower blocked", "shower drain", "shower not draining", "bath blocked",
            "s33",
        ),
        exclude_any=(
            "fair wear and tear", "wear and tear",
            "install fixture", "installed fixture",
            "minor change", "minor improvement",
            "plant trees", "planted trees", "planting trees",
            "alteration", "altered",
            "renovation without consent", "renovate without",
            "healthy homes",
        ),
        forced_sections=("NZLEG/RTA/s45", "NZLEG/RTA/s33"),
        synthetic_query=(
            "landlord responsibility maintain premises reasonable state repair "
            "section 45 habitable condition heating hot water weathertight "
            "residential tenancies act tenant remedies maintenance obligations"
        ),
        notes="Landlord maintenance and repair obligations (s45).",
    ),
    StatuteRoute(
        intent="agreement_form",
        include_any=(
            "tenancy agreement", "written agreement", "copy of agreement",
            "sign agreement", "signing agreement", "before signing",
            "provide agreement", "give the agreement", "before getting the agreement",
            "form of agreement", "written tenancy", "contents of agreement",
            "pet clause", "pets allowed", "no pets", "pets not allowed",
            "cats allowed", "dogs allowed", "cat allowed", "dog allowed",
            "allow pets", "allow cats", "allow dogs",
            "pet policy", "pet bond", "no pet",
            "new pet rules", "suitable for pets", "not suitable for pets",
            "property is not suitable for pets", "property suitable for pets",
            "fish tank", "aquarium", "fish tank permission",
            "change payment date", "change my payment date", "payment date",
            "rent payment date",
            "pet regulations", "pet regulation", "report the landlord", "report landlord",
            "renew our contract", "renew our lease", "renew rental contract",
            "shorter term", "12 month fixed term", "minimum fixed term",
            "new agency", "agency changed", "new property manager", "pm changed",
            "changed property manager", "change of agency", "new pm",
            "pet request", "pet application", "pet approval", "pet request form",
            "age of pet", "age of the cat", "age of the dog", "discriminate on age",
            "have a dog", "have a cat", "have a pet", "want a dog", "want a cat",
            "want a pet", "keep a dog", "keep a cat", "keep a pet",
            "get a dog", "get a cat", "get a pet", "push for a pet",
            "pet cover letter", "applying with a pet", "applying for a house with a pet",
            "pet reference", "pet resume",
            "landlord backed out", "landlord pulled out", "changed their minds",
            "cancelled the tenancy", "pulled out of tenancy", "withdrew the offer",
            "going overseas", "overseas for", "travelling overseas",
            "away for weeks", "away for a month", "leaving the country",
            "add clauses", "adding clauses", "custom clause", "add to agreement",
            "adding to the agreement", "standard rta agreement",
            "payment summary", "rent payment summary", "rent history",
            "proof of rent payments", "proof of payment", "rent record",
            "listing photos", "listing pictures", "rental photos", "rental listing photos",
            "photos of the rental", "different from listing", "photos don't match",
            "old photos", "outdated photos",
        ),
        exclude_any=(
            # Don't fire when the tenant is saying they DON'T have an agreement -
            # that question is about RTA applicability, not agreement contents.
            "no agreement", "no written agreement", "no formal agreement",
            "without agreement", "there is no agreement", "no contract",
            "verbal agreement only", "nothing in writing",
        ),
        forced_sections=("NZLEG/RTA/s13A", "NZLEG/RTA/s13B"),
        synthetic_query=(
            "contents of tenancy agreement landlord obligations provide copy "
            "section 13A written tenancy agreement residential tenancies act"
        ),
        notes="Contents and copy obligations for tenancy agreements (s13A, s13B).",
    ),
    StatuteRoute(
        intent="bond",
        include_any=(
            "bond lodgement", "bond lodged", "lodge the bond", "lodge bond",
            "bond receipt", "proof of bond", "bond proof",
            "bond before", "bond form", "bond help",
            "work and income", "winz", "bond guarantee",
            "can pay the bond", "pay the bond",
            "lodged my bond", "lodged the bond",
            "not lodged", "hasn't lodged", "has not lodged",
            "paid bond", "paid a bond", "paid the bond",
            "paid 1 week bond", "paid 2 weeks bond", "paid 3 weeks bond",
            "paid 4 weeks bond", "took a bond", "bond was taken",
            "bond refund", "refund my bond", "get my bond back", "bond back",
            "bond return", "return my bond", "return the bond",
            "bond refund form", "how long does bond", "bond timeframe",
            "when will i get my bond", "when do i get my bond",
            "bond reduced", "reduce the bond", "bond difference", "difference in bond",
            "bond amount reduced", "rent reduced bond",
            "bond delayed", "bond processing", "how long are bonds",
            "bonds taking", "bond taking", "bond still delayed",
            "holding my bond", "holding the bond", "pm holding bond",
            "how long does a bond", "bond take to be refunded", "bond refund time",
            "bond rejected", "bond application rejected", "bond stuck",
            "no receipts", "without receipts", "didn't provide receipts", "no evidence of costs",
            "send bond", "sent bond", "sent the bond", "submit bond",
            "bond to tenancy", "bond direct", "bond himself", "bond herself",
            "bond number", "bond reference", "bond reference number",
            "different bond number", "wrong bond number",
            "s18",
        ),
        forced_sections=("NZLEG/RTA/s18",),
        synthetic_query=(
            "general bond landlord maximum bond amount four weeks rent section 18 "
            "residential tenancies act bond obligations receipt"
        ),
        notes="General bond requirements - amount limits and receipt (s18).",
    ),
    StatuteRoute(
        intent="landlord_entry",
        include_any=(
            "landlord entry", "landlord enter", "right of entry",
            "inspection notice", "24 hour notice", "24 hours notice",
            "inspection report", "routine inspection",
            "landlord came in", "landlord access",
            "notice before entering", "notice to enter",
            "s48",
            # Homeowner vocabulary - tenants often say "home owner" or "property owner"
            # when the owner lives nearby and acts directly rather than through an agent.
            "home owner", "homeowner", "property owner", "owner of the house",
            "owner of the property", "owner came in", "owner entered",
            "entered my home", "came into my home", "already in my home",
            "was in my home", "was in my house", "was in my flat",
            "uninvited", "is she allowed to do this", "is he allowed to do this",
            "allowed to enter", "allowed to come in",
            "open home", "open homes", "viewings", "property viewing",
            "who is living", "who lives in", "who is residing", "occupants",
            "how many people", "who is staying",
            "prospective tenant", "showing the property", "showing a tenant",
            "showing my property", "showed my property",
            "48 hours notice", "48-hour notice", "48 hour notice",
            "reschedule inspection", "postpone inspection", "cancel inspection",
            "cancelled inspection", "inspection rescheduled", "inspection cancelled",
            "valuer", "valuation", "property valuer", "property valuation",
            "reinspection", "re-inspection", "second inspection", "follow-up inspection",
            "present at inspection", "be present", "attend inspection",
            "inspection time", "change inspection time",
            "inspection standard", "failed inspection", "not up to inspection",
            "insurance inspection", "mortgage valuation", "at owner's request",
            "send someone", "owner's request",
            "take photos", "photos at inspection", "photograph my", "photos of my",
            "final inspection", "exit inspection", "move out inspection",
            "outgoing inspection", "exist inspection",
            "keys handed in", "hand in keys", "handing in keys", "keys handed back",
            "landlord came over", "landlord come over", "landlord showed up",
            "landlord turned up", "turned up unannounced", "came over tonight",
            "came over without notice", "showed up without notice",
            "tested positive", "sick for inspection", "covid inspection",
            "ill for inspection", "unwell for inspection", "postpone due to",
            "delay inspection due",
            "notified yesterday", "notice yesterday", "told yesterday",
            "less than 24 hours notice", "less than 24 hours",
            "only one day notice", "only 1 day notice",
        ),
        forced_sections=("NZLEG/RTA/s48",),
        synthetic_query=(
            "landlord right of entry inspection notice 24 hours section 48 "
            "residential tenancies act access premises"
        ),
        notes="Landlord entry and inspection rules (s48).",
    ),
    StatuteRoute(
        intent="sham_flatmate_agreement",
        include_any=(
            "flatmate agreement", "flatmate arrangement",
            "boarder agreement", "boarder arrangement",
            "licence agreement", "licensee",
            "not a tenant", "not tenants", "are we tenants",
            "meant to be tenants", "should be tenants",
            "landlord not living", "landlord lives elsewhere",
            "landlord doesn't live", "landlord does not live",
            "landlord not resident", "landlord not there",
            "s5",
            "sublet", "subletting", "sublease", "sub-letting", "sub-lease",
            "renting from a flatmate", "paying my flatmate", "flatmate charges",
            "flatmate is my landlord", "room from a flatmate",
            "he pays the landlord", "she pays the landlord",
            "paying through my flatmate", "pays the landlord for me",
        ),
        forced_sections=("NZLEG/RTA/s5",),
        synthetic_query=(
            "flatmate boarder licensee agreement landlord not resident sham tenancy "
            "RTA applies despite flatmate agreement section 5 definition residential "
            "tenancy landlord not living premises tenant rights wrongful agreement"
        ),
        case_synthetic_query=(
            "flatmate agreement landlord not living property sham tenancy RTA applies "
            "boarder licensee residential tenancy act tenant rights eviction notice "
            "invalid agreement landlord not resident"
        ),
        notes="Sham flatmate/boarder agreements where landlord is not resident (s5).",
    ),
    StatuteRoute(
        intent="termination_notice",
        include_any=(
            "evict", "eviction",
            "notice to leave", "notice to vacate",
            "end the tenancy", "end my tenancy", "terminate tenancy",
            "90 day notice", "90 days notice", "90-day notice",
            "42 day notice", "42 days notice", "42-day notice",
            "21 day notice", "21 days notice",
            "periodic tenancy end", "asked to leave",
            "termination notice", "s51", "s56",
            "gave notice", "given notice", "i gave notice",
            "gave me notice", "given me notice", "received a notice", "received notice",
            "signed a variation", "tenancy variation", "variation agreement",
            "give notice", "giving notice", "handing in my notice", "hand in my notice",
            "minimum notice", "how much notice", "how many days notice",
            "moving out notice", "notice to move out", "notice period",
            "drop keys off", "key return", "return the keys", "hand keys back",
            "extra days rent", "public holiday", "easter monday", "easter friday",
            "resign lease", "re-sign lease", "resign the lease", "re-sign the lease",
            "renew the lease", "renew lease", "forced to renew",
            "go periodic", "go to periodic", "switch to periodic", "convert to periodic",
            "periodic instead", "periodic after fixed", "stay periodic",
            "end of fixed term", "fixed term ending", "fixed term expires",
            "change the locks", "changed the locks", "change locks", "lock change",
            "change my locks", "changed my locks", "new locks",
        ),
        forced_sections=("NZLEG/RTA/s51",),
        synthetic_query=(
            "landlord terminate periodic tenancy notice 90 days 42 days "
            "section 51 residential tenancies act tenant notice 21 days "
            "lawful grounds termination"
        ),
        notes="Termination of periodic tenancy, notice periods (s51).",
    ),
    StatuteRoute(
        intent="fixed_term_sell",
        include_any=(
            "fixed term tenancy sell", "fixed-term tenancy sell",
            "sell the house", "sell the property", "want to sell",
            "selling the house", "selling the property",
            "list the property", "list the house", "before listing",
            "vacant possession", "empty before", "vacant before",
            "fixed term end early", "break fixed term",
            "putting the property up for sale", "putting property up for sale",
            "putting it up for sale", "going up for sale", "going on the market",
        ),
        forced_sections=("NZLEG/RTA/s60A", "NZLEG/RTA/s50"),
        synthetic_query=(
            "landlord fixed term tenancy sell house vacant possession terminate early "
            "mutual agreement section 50 section 60A periodic tenancy notice "
            "residential tenancies act tenant rights fixed term expiry"
        ),
        notes="Landlord wants to sell with vacant possession during fixed-term (s60A, s50).",
    ),
    StatuteRoute(
        intent="healthy_homes",
        include_any=(
            "healthy homes", "healthy home", "hhs",
            "heating standard", "heating requirement", "minimum heating",
            "insulation standard", "ceiling insulation", "underfloor insulation",
            "ventilation standard", "extractor fan", "extraction fan",
            "moisture barrier", "ground moisture", "draught stopping",
            "draught standard", "draughts", "no insulation",
            "how does healthy homes", "how often checked", "healthy homes compliance",
            "healthy homes certificate", "compliance statement",
            "s138b", "s45b", "s66i",
        ),
        forced_sections=(
            "NZLEG/RTA/s138B",
            "NZLEG/HHS2019/s8",   # heating: main living room qualifying heater
            "NZLEG/HHS2019/s14",  # insulation: qualifying ceiling insulation
            "NZLEG/HHS2019/s21",  # ventilation: openable windows/doors
            "NZLEG/HHS2019/s23",  # ventilation: extraction fans in kitchens and bathrooms
            "NZLEG/HHS2019/s26",  # draught: gaps and holes
            "NZLEG/HHS2019/s28",  # moisture: ground moisture barrier
        ),
        synthetic_query=(
            "healthy homes standards heating insulation ventilation moisture draught "
            "residential tenancies act section 138B landlord obligations "
            "extractor fan ceiling underfloor insulation draught stopping ground moisture barrier"
        ),
        notes="Healthy Homes Standards - heating, insulation, ventilation, moisture, draught (HHS2019).",
    ),
    StatuteRoute(
        intent="healthy_homes_facilities",
        include_any=(
            "carport light", "laundry light", "no light", "lighting in",
            "lights in", "lights at", "adequate lighting", "working lights",
            "smoke alarm", "carbon monoxide",
        ),
        forced_sections=(
            "NZLEG/HHS2019/s21",  # ventilation: openable windows/doors
            "NZLEG/HHS2019/s23",  # ventilation: extraction fans in kitchens and bathrooms
            "NZLEG/HHS2019/s24",  # exemption from mechanical ventilation standard
        ),
        synthetic_query=(
            "landlord obligations lighting smoke alarm carport laundry "
            "healthy homes standards ventilation extraction fan requirements "
            "habitable space facilities residential tenancy"
        ),
        notes="HHS facilities: lighting, smoke alarms - forces ventilation sections as grounding context.",
    ),
    StatuteRoute(
        intent="rent_increase",
        include_any=(
            "rent increase", "increase the rent", "raise the rent", "raised the rent",
            "increased the rent", "increased my rent",
            "increase my rent", "increase rent", "increasing rent", "increasing my rent",
            "rent rise", "rent review", "maximum rent", "rent in advance",
            "weeks rent in advance", "how much rent", "notice to increase",
            "s28", "s28a",
        ),
        forced_sections=("NZLEG/RTA/s28", "NZLEG/RTA/s28A"),
        synthetic_query=(
            "notice to increase rent landlord section 28 28A residential tenancies act "
            "rent increase order unforeseen expenses 90 days"
        ),
        notes="Rent increases by notice or order (s28, s28A).",
    ),
    StatuteRoute(
        intent="fixed_term_rent_review",
        include_any=(
            "rent review", "rent increase", "increase the rent", "raise the rent",
            "review clause", "rent review clause", "rent will increase",
            "rent going up", "review in", "increase at review",
        ),
        include_all=("fixed term",),
        forced_sections=("NZLEG/RTA/s13A", "NZLEG/RTA/s50"),
        synthetic_query=(
            "fixed term tenancy rent review clause agreement contents section 13A "
            "landlord must specify review method limit mutual termination section 50 "
            "tenant options fixed term unable to pay increased rent"
        ),
        notes=(
            "Fixed-term tenancy with a rent review clause. "
            "s13A=agreement must clearly specify review terms (if silent, increase is invalid); "
            "s50=early exit options if tenant cannot afford the increase."
        ),
    ),
    StatuteRoute(
        intent="tenant_early_exit",
        include_any=(
            "leave early", "leave the tenancy early", "end the tenancy early",
            "move out before", "moving out before", "get out of the tenancy",
            "exit the lease", "exit the tenancy", "break the lease",
            "break lease", "breaking lease", "breaking the lease",
            "break fixed term lease", "breaking fixed term", "lease break",
            "lease break fee", "break fee", "break lease costs",
            "job offer", "new job", "job opportunity", "farm job",
            "relocating", "moving city", "moving town", "moving region",
            "partner got a job", "offered a job", "offered housing",
            "how do i get out", "how to get out", "how can i leave",
            "want to leave", "want to move out", "need to move out",
            "early termination tenant", "tenant terminate early",
        ),
        forced_sections=("NZLEG/RTA/s50", "NZLEG/RTA/s66"),
        synthetic_query=(
            "tenant fixed term tenancy leave early mutual agreement landlord consent "
            "section 50 termination agreement section 66 assignment subletting "
            "replacement tenant liability rent fixed term break lease early exit"
        ),
        notes="Tenant wants to leave a fixed-term early (job, relocation, hardship). s50=mutual termination, s66=assignment.",
    ),
    StatuteRoute(
        intent="carpark_dispute",
        include_any=(
            "carpark", "car park", "car parks", "carparks",
            "parking space", "parking spaces", "parking bay",
            "parking included", "park my car", "use the garage",
            "garage included", "remove carpark", "lose carpark",
            "take away carpark", "vacate carpark", "vacate the carpark",
        ),
        forced_sections=("NZLEG/RTA/s45", "NZLEG/RTA/s13A"),
        synthetic_query=(
            "landlord remove carpark parking space included tenancy agreement "
            "tenant facilities services agreed quiet enjoyment obligation "
            "section 45 landlord obligation section 13A tenancy agreement contents "
            "rent reduction loss of amenity agreed services"
        ),
        leg_allow_list=("NZLEG/RTA/s45", "NZLEG/RTA/s13A"),
        notes="Carpark/parking dispute - landlord removing agreed facility. s45=landlord obligations, s13A=tenancy agreement contents.",
    ),
    StatuteRoute(
        intent="family_violence_exit",
        include_any=(
            "protection order", "domestic violence", "family violence",
            "family harm", "violence order", "dv order",
            "women's refuge", "womens refuge", "refuge",
            "feeling unsafe at home", "unsafe in my home",
            "abusive partner", "abusive relationship",
            "s55b", "s55c",
        ),
        forced_sections=("NZLEG/RTA/s55B", "NZLEG/RTA/s55C"),
        synthetic_query=(
            "tenant family violence domestic violence protection order "
            "terminate tenancy early section 55B 55C residential tenancies act "
            "victim safety notice without consent co-tenant"
        ),
        notes="Family violence exit - tenant can terminate without notice using s55B/s55C.",
    ),
    StatuteRoute(
        intent="quiet_enjoyment",
        include_any=(
            "quiet enjoyment", "peaceful enjoyment", "peaceful possession",
            "s38",
            "harass", "harassment", "landlord harassing",
            "interfere with my belongings", "interfere with my possessions",
            "interfere with my stuff", "interfering with my",
            "get rid of my belongings", "get rid of my furniture", "remove my belongings",
            "forced to remove", "remove my stuff",
            "noisy neighbour", "noisy neighbor", "noisy neighbours", "noisy neighbors",
            "violent neighbour", "violent neighbor", "violent neighbours", "violent neighbors",
            "threatening neighbour", "threatening neighbor",
            "disruptive neighbour", "disruptive neighbor",
            "neighbour harassment", "neighbor harassment",
            "neighbour dispute", "neighbor dispute",
            "construction noise", "building works next door", "renovation next door",
            "noise complaint", "noise from neighbour", "noise from neighbor",
            "neighbour making noise", "neighbor making noise",
            "painters in my", "contractors in my", "workmen in my",
            "rent reduction", "lower my rent", "lower the rent", "reduce my rent",
            "rent lowered", "rent should be reduced",
            "curtains missing", "no curtains", "lack of privacy", "privacy curtains",
            "sleep out", "sleep-out", "sleepout", "outbuilding",
            "landlord storing", "storing in my", "storing items in",
        ),
        forced_sections=("NZLEG/RTA/s38",),
        synthetic_query=(
            "landlord obligation quiet enjoyment tenant peaceful possession "
            "section 38 residential tenancies act interference harassment "
            "noisy disruptive neighbours landlord must not interfere"
        ),
        notes="Quiet enjoyment - landlord must not interfere with tenant's peaceful possession (s38).",
    ),
    StatuteRoute(
        intent="tribunal_process",
        include_any=(
            "tenancy tribunal today", "applying to the tribunal", "apply to the tribunal",
            "apply to tribunal", "tribunal application", "tribunal process",
            "how does tribunal work", "how to apply to tribunal",
            "never done tribunal", "never been to tribunal", "never used tribunal",
            "file at tribunal", "file a claim", "lodge a claim",
            "evidence for tribunal", "provide evidence", "evidence at tribunal",
            "how do i apply", "what do i need for tribunal",
            "mediation", "hearing date", "tribunal hearing",
            "s85", "s86",
            "court order", "tribunal order", "order from tribunal",
            "going to court", "court tomorrow", "court today",
            "in court", "at court", "court hearing", "at the tribunal",
            "legal battle", "breach of tenancy", "breach of the tenancy",
            "repeat offender", "negligence",
            "applied to tribunal", "applied to the tribunal",
            "application to tenancy tribunal", "submitted an application",
            "tribunal address", "tribunal location", "where is the tribunal",
            "summoned to tribunal", "summoned to the tribunal", "tribunal summons",
            "going to tribunal", "going to the tribunal", "before the tribunal",
            "hard copies", "evidence submitted", "print out evidence",
            "timeframe to file", "time limit to apply", "deadline to apply",
            "how long to file", "how long to apply", "time to file",
            "appeal tribunal", "appeal the decision", "appeal to district court",
            "appealed tribunal", "appealed the decision",
            "false allegations", "false allegation", "false statements",
            "false evidence", "false rental reference", "false reference",
            "misleading tribunal", "lies at tribunal", "lied at tribunal",
            "spreading misinformation", "false information",
        ),
        forced_sections=("NZLEG/RTA/s85", "NZLEG/RTA/s86"),
        synthetic_query=(
            "tenancy tribunal application process how to apply jurisdiction "
            "section 85 86 evidence mediation hearing residential tenancies act "
            "tenant landlord dispute claim procedure"
        ),
        notes="Tenancy Tribunal application process, evidence, hearings (s85, s86).",
    ),
    StatuteRoute(
        intent="water_charges",
        include_any=(
            "water bill", "water bills", "water charges", "water charge",
            "water usage", "water account", "water meter",
            "pay the water", "liable for water", "responsible for water",
            "water rates", "metered water", "water costs",
            "pay water", "water and waste", "wastewater", "water waste",
            "gas bottle", "gas bottle rental", "gas bottle fee", "gas bottle cost",
            "s36",
        ),
        forced_sections=("NZLEG/RTA/s36",),
        synthetic_query=(
            "landlord water charges tenant liable metered water supply "
            "section 36 residential tenancies act water bill payment "
            "water usage responsibility"
        ),
        notes="Water charge liability between landlord and tenant (s36).",
    ),
    StatuteRoute(
        intent="rent_arrears",
        include_any=(
            "rent arrears", "arrears", "rent overdue", "overdue rent",
            "behind on rent", "behind in rent", "owe rent", "owes rent",
            "rent is behind", "rent behind", "behind with rent", "rent is overdue",
            "flatmate not paying", "flatmate misses paying", "flatmate owes",
            "flatmate missed rent", "flatmate behind on rent",
            "14 day notice", "14-day notice", "arrears notice",
            "notice for arrears", "unpaid rent", "missed rent",
            "rent not paid", "failed to pay rent",
            "s55", "s56",
        ),
        forced_sections=("NZLEG/RTA/s55", "NZLEG/RTA/s27"),
        synthetic_query=(
            "tenant rent arrears unpaid rent landlord 14 day notice "
            "section 55 termination application tribunal section 27 "
            "rent payment obligation residential tenancies act"
        ),
        notes="Rent arrears, 14-day notice, termination for non-payment (s55, s27).",
    ),
]

LOW_PRIORITY_SECTIONS: dict[str, tuple[str, ...]] = {
    # Structural suppression: s16A is almost never relevant. Overseas landlord
    # queries are rare and have distinctive vocabulary, so keyword gate is reliable.
    # Word-sense false positives (e.g. "security camera" pulling bond sections) are
    # handled by the cross-encoder gate in anchor.py, not here.
    "NZLEG/RTA/s16A": (
        "landlord overseas", "landlord out of new zealand",
        "agent if landlord", "21 consecutive days",
        "out of new zealand", "overseas landlord",
    ),
    # s55AA: termination by notice for physical assault by tenant.
    # CE scores ~0.58 on relationship-breakdown and repeated-breach questions
    # because "termination" semantics overlap. Suppress unless the question
    # actually involves violence or physical harm.
    "NZLEG/RTA/s55AA": (
        "assault", "physical assault", "attacked", "attack",
        "violence", "violent", "threatened", "threat",
        "hit", "punched", "kicked", "hurt", "injured", "harm",
    ),
}
