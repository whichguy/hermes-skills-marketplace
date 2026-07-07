# Privacy Audit Patterns

Regex patterns for scanning skills before publishing. Run these against every
file in the skill directory. Any match = must sanitize before publishing.

## Personal Identifiers

```python
PATTERNS = {
    # Email addresses (exclude example.com, github.com, generic domains)
    "Email (personal)": r'[a-zA-Z0-9._%+-]+@(?!example\.com|y\.com|github\.com|noreply)[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}',
    
    # Phone numbers (10+ digits, or formatted US numbers)
    "Phone": r'(\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}',
    "Phone (raw digits)": r'\b\d{10,}\b',
    
    # WhatsApp/messaging group IDs
    "WhatsApp group": r'\d{15,}@g\.us',
    
    # IP addresses (exclude localhost)
    "IP (non-localhost)": r'\b(?!127\.0\.0\.1|0\.0\.0\.0|255\.)\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b',
}
```

## Location Patterns

```python
LOCATION_PATTERNS = {
    # Street addresses
    "Street address": r'\d{3,5}\s+[A-Z][a-z]+\s+(St|Ave|Blvd|Dr|Rd|Ln|Way|Ct|Cir)\b',
    
    # ZIP codes (5 digits in context)
    "ZIP code": r'\b\d{5}\b',
    
    # City names — add your own to this list
    "Home city": r'(?i)san\s+ramon',  # example — replace with user's city
}
```

## Personal Names & Organizations

```python
# Build this list from the user's memory entries
SENSITIVE_STRINGS = [
    # Family names
    "Family Member Wiese", "ExampleName Wiese", "ExampleName Wiese",
    # Professional contacts
    "Wallin", "Eustis", "Stephanie",
    # Organization domains
    "fortifiedstrength.org", "canyoncreekchurch.org",
    # Personal venues
    "Ed Robson", "Hyatt Regency",
    # Service providers
    "DirecTV",
    # Athletes/associates
    "ExampleName",
]
```

## Financial

```python
FINANCIAL_PATTERNS = {
    "Credit card": r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b',
    "SSN": r'\b\d{3}-\d{2}-\d{4}\b',
}
```

## Secrets (real tokens only, not placeholders)

```python
SECRET_PATTERNS = {
    "OpenAI key": r'sk-[a-zA-Z0-9]{20,}',
    "GitHub token": r'gh[pousr]_[a-zA-Z0-9]{36,}',
    "Google API key": r'AIza[a-zA-Z0-9_-]{35}',
    "Slack token": r'xox[baprs]-[a-zA-Z0-9-]+',
    "AWS key": r'AKIA[0-9A-Z]{16}',
    "Private key": r'-----BEGIN (RSA |EC )?PRIVATE KEY-----',
}
```

## Replacement Strategy

For each match:
1. Extract the personal value
2. Write it to `config.yaml` under `skills.config.<key>` 
3. Replace in the published skill with a generic default
4. Re-audit to confirm zero matches

## Decision: Publish vs Keep Private

Keep a skill private (don't publish) if:
- It contains a relationship graph or personal context model
- It contains personal schedule/timeline details
- It contains cron job IDs or delivery channel identifiers
- Its core function is managing the user's personal life