from seleniumbase import SB

with SB(uc=True, test=True) as sb:
    sb.open("https://www.google.com")
    print("DZIALA:", sb.get_title())