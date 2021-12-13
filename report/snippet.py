import re
import nltk
import contractions
def preprocess(text):
    text = text.encode('ascii','ignore').decode()                                       # 9. remove non ascii characters
    text = re.sub("[\[\(\{].*?[\]\)\}]", " ", text)                                     # 1. remove words in the parentheses
    text = re.sub("\S*@\S*\s?|(http[s]?S+)|(w+.[A-Za-z]{2,4}S*)", " ", text)            # 2. remove email address and ur.s
    text = text.lower()                                                                 # 3. lower
    text = re.sub("u.s."," usa ",text)                                                  # 4. corner case u.s. (appeared 15052 times..!)
    text = re.sub("north korea|n. korea|n. k.","nkorea",text)                           # 5. corner case n.korea 
    text = re.sub("south korea|s. korea|s. k.","skorea",text)                           # 6. corner case s.korea
    text = text.replace("'s", " ")                                                      # 7. remove apostrophes with s (it appears a lot)
    text = text.replace(".",". ")                                                       # 8. sentence seperate problem
    text = contractions.fix(text)                                                       # 10. expand contractions
    text = re.sub("[^\w. -]|_", " ", text)                                              # 11. erase except -, ., alphanumerics
    text= " ".join([word for word in str(text).split() if word not in STOPWORDS])       # 12. remove stopwords
    return text