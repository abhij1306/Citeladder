"""Golden onboarding cases whose buyer walks away with a PRODUCT.

Marketplaces, retailers and D2C brands. Split from
:mod:`evaluations.onboarding_cases` because one file of hand-authored
cases outgrew the module ceiling; the product/service boundary is the axis
the corpus exists to test, so it is the one the split follows.
See :mod:`evaluations.onboarding_corpus` for the schema.
"""

from __future__ import annotations

from evaluations.onboarding_corpus import GoldenOnboardingCase

_FLIPKART = GoldenOnboardingCase(
    slug="flipkart-india",
    brand_name="Flipkart",
    primary_market="India",
    website_url="https://www.flipkart.com",
    sector="Retail and Ecommerce",
    category="general merchandise online marketplace",
    category_aliases=(
        "online shopping site",
        "ecommerce marketplace",
        "online store",
        "shopping app",
    ),
    business_model="marketplace",
    market_scope="national",
    buyer_type="b2c",
    knowledge_strength="strong",
    jobs_to_be_done=(
        "buy a product online at the lowest price",
        "get fast and reliable delivery",
        "avoid counterfeit products",
        "pay in instalments",
    ),
    category_terms=(
        "online shopping",
        "mobile phones",
        "consumer electronics",
        "fashion and apparel",
        "home appliances",
        "cash on delivery",
    ),
    expected_competitors=(
        "Amazon India",
        "Meesho",
        "JioMart",
        "Myntra",
        "Tata CLiQ",
    ),
    buyer_register="terse_transactional",
    gold_buyer_prompts=(
        "best site to buy electronics online in india",
        "where to buy original branded shoes online india",
        "which online shopping app has fastest delivery in india",
        "cheapest place to buy iphone in india online",
        "safest online shopping site india for expensive items",
        "which ecommerce site has best return policy in india",
        "online shopping sites with cash on delivery india",
        "best online store for mobile phones with exchange offer",
        "where can i buy genuine products online without fakes india",
        "which shopping app gives the best discount during sale",
        "online marketplace with easy emi options india",
        "best site for buying home appliances online india",
    ),
    gold_branded_prompts=(
        "is flipkart or amazon better for electronics",
        "is flipkart reliable for buying phones",
        "flipkart vs meesho for cheap clothes",
        "does flipkart sell original products",
        "is flipkart big billion days actually worth it",
    ),
    products_or_services=("online shopping", "electronics", "fashion"),
    use_cases=("buy products online", "compare prices", "home delivery"),
    market_terms=("india", "indian", "inr"),
)


_BEST_AND_LESS = GoldenOnboardingCase(
    slug="best-less-australia",
    brand_name="Best&Less",
    primary_market="Australia",
    website_url="https://www.bestandless.com.au",
    sector="Retail and Ecommerce",
    category="value fashion and kids clothing retailer",
    category_aliases=(
        "budget clothing store",
        "affordable kids clothes",
        "discount fashion retailer",
        "cheap family clothing",
    ),
    business_model="retail",
    market_scope="national",
    buyer_type="b2c",
    knowledge_strength="strong",
    jobs_to_be_done=(
        "clothe a family on a budget",
        "buy school uniforms cheaply",
        "replace kids clothes as they grow",
        "buy basic homewares affordably",
    ),
    category_terms=(
        "school uniforms",
        "kids clothing",
        "baby clothes",
        "womens basics",
        "homewares",
        "sleepwear",
    ),
    expected_competitors=(
        "Kmart Australia",
        "BIG W",
        "Target Australia",
        "Cotton On",
        "Bonds",
    ),
    buyer_register="terse_transactional",
    gold_buyer_prompts=(
        "cheap school uniforms australia",
        "where to buy affordable baby clothes australia",
        "best budget clothing stores australia",
        "cheapest place to buy kids clothes in australia",
        "affordable womens basics australia online",
        "good quality cheap towels and sheets australia",
        "where to buy school shoes cheap australia",
        "budget maternity clothes australia",
        "discount clothing stores near me australia",
        "best value pyjamas for kids australia",
        "cheap mens work clothes australia",
        "affordable homewares store australia",
    ),
    gold_branded_prompts=(
        "is best and less good quality",
        "best and less vs kmart for kids clothes",
        "does best and less have online shopping",
        "best and less school uniform review",
        "is best and less cheaper than target australia",
    ),
    products_or_services=("affordable clothing", "kids clothing", "homewares"),
    use_cases=("family essentials", "school clothes", "budget fashion"),
    market_terms=("australia", "australian", "aud"),
)


_PUMA = GoldenOnboardingCase(
    slug="puma-india",
    brand_name="Puma",
    primary_market="India",
    website_url="https://in.puma.com",
    sector="Retail and Ecommerce",
    category="sportswear and athletic footwear brand",
    category_aliases=(
        "running shoes brand",
        "sports shoes",
        "athletic wear",
        "sneakers brand",
    ),
    business_model="d2c_product",
    market_scope="national",
    buyer_type="b2c",
    knowledge_strength="strong",
    jobs_to_be_done=(
        "find running shoes that suit my gait and budget",
        "buy gym and training wear",
        "buy sneakers for everyday wear",
        "replace worn-out sports shoes",
    ),
    category_terms=(
        "running shoes",
        "sports shoes",
        "sneakers",
        "training wear",
        "athletic footwear",
        "track pants",
    ),
    expected_competitors=(
        "Adidas India",
        "Nike India",
        "Skechers India",
        "ASICS India",
        "New Balance India",
    ),
    buyer_register="terse_transactional",
    gold_buyer_prompts=(
        "best running shoes under 5000 india",
        "good sports shoes for gym india",
        "best sneakers for daily wear india",
        "comfortable running shoes for beginners india",
        "best athletic wear brands in india",
        "durable sports shoes for marathon training india",
        "best budget sports shoes for college students",
        "which brand has the best cushioning running shoes india",
        "sports shoes with good grip for treadmill",
        "best track pants for gym india",
        "affordable branded sneakers india online",
        "best shoes for flat feet running india",
    ),
    gold_branded_prompts=(
        "puma vs adidas running shoes india",
        "is puma good quality for running",
        "puma vs nike which is better value india",
        "are puma shoes worth the price",
        "puma running shoes review india",
    ),
    products_or_services=("sportswear", "running shoes", "athletic footwear"),
    use_cases=("running", "training", "everyday sneakers"),
    market_terms=("india", "indian", "inr"),
)


_GRAZA = GoldenOnboardingCase(
    slug="graza-united-states",
    brand_name="Graza",
    primary_market="United States",
    website_url="https://www.graza.co",
    sector="Food and Beverage",
    category="single-origin extra virgin olive oil brand",
    category_aliases=(
        "olive oil brand",
        "extra virgin olive oil",
        "cooking oil",
        "finishing oil",
    ),
    business_model="d2c_product",
    market_scope="national",
    buyer_type="b2c",
    # The small-brand case.  This is the vayudoot.in analogue: the model knows
    # little, so the profile must lean on site evidence and honestly report low
    # confidence rather than inventing a plausible-sounding business.
    knowledge_strength="weak",
    jobs_to_be_done=(
        "buy olive oil that is actually fresh and real",
        "have separate oils for cooking and finishing",
        "find a good gift for someone who cooks",
        "avoid adulterated supermarket olive oil",
    ),
    category_terms=(
        "extra virgin olive oil",
        "finishing olive oil",
        "cooking olive oil",
        "single origin olive oil",
        "harvest date olive oil",
        "squeeze bottle olive oil",
    ),
    expected_competitors=(
        "Brightland",
        "Kosterina",
        "California Olive Ranch",
        "Fat Gold",
        "Wonder Valley",
    ),
    buyer_register="research_comparative",
    gold_buyer_prompts=(
        "best olive oil for cooking and finishing",
        "good everyday olive oil brand",
        "best extra virgin olive oil for salad dressing",
        "which olive oil brands are actually real and not fake",
        "best olive oil in a squeeze bottle",
        "high quality olive oil for gifting",
        "single origin olive oil brands usa",
        "best olive oil for high heat cooking",
        "olive oil subscription usa",
        "fresh olive oil brands with a harvest date",
        "best tasting finishing olive oil",
        "affordable good olive oil that is not from the supermarket",
    ),
    gold_branded_prompts=(
        "is graza olive oil good",
        "graza drizzle vs sizzle",
        "graza olive oil review",
        "is graza worth the price",
        "graza vs brightland olive oil",
    ),
    products_or_services=(
        "extra virgin olive oil",
        "finishing olive oil",
        "cooking olive oil",
    ),
    use_cases=("everyday cooking", "finishing dishes", "gifting"),
    market_terms=("united states", "u.s.", "us market", "usa"),
)


_WAKEFIT = GoldenOnboardingCase(
    slug="wakefit-india",
    brand_name="Wakefit",
    primary_market="India",
    website_url="https://www.wakefit.co",
    sector="Retail and Ecommerce",
    category="direct-to-consumer mattress and home furniture brand",
    category_aliases=(
        "mattress brand",
        "memory foam mattress",
        "orthopedic mattress",
        "online mattress",
    ),
    business_model="d2c_product",
    market_scope="national",
    buyer_type="b2c",
    knowledge_strength="strong",
    jobs_to_be_done=(
        "fix back pain caused by a bad mattress",
        "buy a mattress online without lying on it first",
        "furnish a home affordably",
        "replace a sagging old mattress",
    ),
    category_terms=(
        "orthopedic mattress",
        "memory foam mattress",
        "queen size mattress",
        "bed frames",
        "study tables",
        "mattress trial period",
    ),
    expected_competitors=(
        "Sleepwell",
        "Duroflex",
        "Kurlon",
        "SleepyCat",
        "Pepperfry",
    ),
    buyer_register="research_comparative",
    gold_buyer_prompts=(
        "best mattress for back pain india under 20000",
        "memory foam vs spring mattress which is better",
        "best orthopedic mattress india",
        "which mattress is best for side sleepers india",
        "queen size mattress price india online",
        "best mattress brand india",
        "mattress with trial period india",
        "firm vs medium firm mattress for back pain",
        "best budget mattress india online",
        "how long does a foam mattress last",
        "best mattress for couples india",
        "affordable study table and chair online india",
    ),
    gold_branded_prompts=(
        "is wakefit mattress good",
        "wakefit vs sleepwell",
        "wakefit orthopedic memory foam review",
        "wakefit vs duroflex mattress",
        "is wakefit worth buying",
    ),
    products_or_services=("mattresses", "bed frames", "home furniture"),
    use_cases=("relieve back pain", "furnish a home", "buy a mattress online"),
    market_terms=("india", "indian", "inr"),
)


_BURROW = GoldenOnboardingCase(
    slug="burrow-united-states",
    brand_name="Burrow",
    primary_market="United States",
    website_url="https://burrow.com",
    sector="Retail and Ecommerce",
    category="modular direct-to-consumer sofa and furniture brand",
    category_aliases=(
        "modular sofa",
        "sectional couch",
        "direct to consumer furniture",
        "apartment furniture",
    ),
    business_model="d2c_product",
    market_scope="national",
    buyer_type="b2c",
    knowledge_strength="weak",
    jobs_to_be_done=(
        "get a sofa into a small apartment",
        "buy furniture that survives pets and kids",
        "assemble furniture without tools or help",
        "expand a couch later without replacing it",
    ),
    category_terms=(
        "modular sofa",
        "sectional couch",
        "sleeper sofa",
        "apartment furniture",
        "washable upholstery",
        "tool-free assembly",
    ),
    expected_competitors=(
        "Article",
        "Floyd",
        "Joybird",
        "Interior Define",
        "West Elm",
    ),
    buyer_register="research_comparative",
    gold_buyer_prompts=(
        "best modular sofa for a small apartment",
        "sectional couch that is easy to move",
        "best sofa for an apartment with a narrow doorway",
        "durable couch for pets and kids",
        "best direct to consumer furniture brands",
        "sofa you can assemble yourself without tools",
        "best washable couch cover sofa",
        "mid century modern sofa under 2000",
        "couch with fast shipping usa",
        "best sleeper sofa for guests in a small space",
        "modular couch you can add sections to later",
        "good quality sofa that ships in a box",
    ),
    gold_branded_prompts=(
        "is burrow furniture worth it",
        "burrow vs article sofa",
        "burrow sofa review durability",
        "burrow vs floyd couch",
        "is the burrow sofa comfortable",
    ),
    products_or_services=("modular sofas", "sectionals", "apartment furniture"),
    use_cases=("furnish a small space", "buy a durable couch", "easy assembly"),
    market_terms=("united states", "u.s.", "us market", "usa"),
)


# The corpus had eleven cases and not one service business, which is how a
# services firm shipped as a product vendor. Valtech is the shape that breaks:
# its site advertises the categories it WORKS IN ("commerce", "experience",
# "data"), so a careless read names the product category and then hands back the
# platforms Valtech implements -- Shopify Plus, SAP Commerce Cloud, commercetools
# -- as competitors. Every one of those scores high on substitutability, use-case
# overlap, geography and question visibility, so only a check on the *kind* of
# company rejects them. `expected_competitors` is therefore all agencies, and
# `unexpected` in the competitor evaluation is where that failure now shows up.


COMMERCE_CASES: tuple[GoldenOnboardingCase, ...] = (
    _FLIPKART,
    _BEST_AND_LESS,
    _PUMA,
    _GRAZA,
    _WAKEFIT,
    _BURROW,
)
