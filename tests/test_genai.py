from google.genai import types
import inspect

print("Part.from_text signature:", inspect.signature(types.Part.from_text))

try:
    p1 = types.Part.from_text("hello")
    print("p1 works!")
except Exception as e:
    print("p1 error:", e)

try:
    p2 = types.Part.from_text(text="hello")
    print("p2 works!")
except Exception as e:
    print("p2 error:", e)

