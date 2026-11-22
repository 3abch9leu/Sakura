"""
Plant-care recommendations from a leaf analysis (team DeepLabV3 segmentation + simple colour measurements)
and, when available, the local weather. Rules, not a diagnosis: every suggestion says what to check.

Inputs measured on the photo:
  * affected share, number of areas and their mean size (from the lesion mask)
  * lesion colour: dark brown / black (necrosis), tan / grey, or yellow (chlorosis)
  * yellowing of the remaining leaf (green vs yellow tissue)
Context: plant species (INBETWEEN plants), forecast humidity / rain / heat.
"""
import cv2
import numpy as np

# What each INBETWEEN plant commonly shows; phrased as "check", never as a diagnosis.
PLANT_NOTES = {
    "basil": {
        "spots": "Basil commonly gets downy mildew (yellowing between veins, grey-purple fuzz under the leaf) and leaf spot.",
        "check": "Turn a leaf over: grey or purple fuzz underneath points to downy mildew, which spreads fast in humid air.",
    },
    "mint": {
        "spots": "Mint commonly shows rust (small orange-brown pustules, mostly under the leaves) or leaf spot.",
        "check": "Rub a spot with a tissue: orange powder points to rust. Remove those stems at the base.",
    },
    "cherry_tomato": {
        "spots": "Tomato leaves commonly show early blight (brown spots with rings, from the lowest leaves up) or late blight "
                 "(large greasy grey-brown patches in cool, wet weather).",
        "check": "Look at the lowest leaves first and at the stems: dark patches on stems in wet weather need fast action.",
    },
    "strawberry": {
        "spots": "Strawberry leaves commonly show leaf spot (small purple-edged spots) or leaf scorch (purple-brown blotches).",
        "check": "Check whether the spots have a pale centre and a purple border; remove old leaves after fruiting.",
    },
    "lettuce": {
        "spots": "Lettuce commonly gets downy mildew (pale angular patches, white growth underneath) and tip burn from heat.",
        "check": "Brown leaf edges in hot weather are usually tip burn (water and heat stress), not a disease.",
    },
    "parsley": {
        "spots": "Parsley commonly shows Septoria leaf spot (small brown spots with tiny black dots) in damp weather.",
        "check": "Tiny black dots inside the spots point to a fungal leaf spot: remove the affected leaves.",
    },
    "chili": {
        "spots": "Chili leaves commonly show bacterial spot (small dark water-soaked spots) or sunscald on fruit.",
        "check": "Water-soaked spots that turn dark and tear point to a bacterial problem: avoid touching wet plants.",
    },
}


def measure(rgb, lesion, tissue):
    """Colour and shape measurements that the advice uses."""
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    h, s, v = hsv[..., 0].astype(float), hsv[..., 1].astype(float), hsv[..., 2].astype(float)
    out = {"lesion_tone": None, "yellowing_share": 0.0, "mean_area_share": 0.0, "largest_area_share": 0.0}
    healthy = tissue & ~lesion
    if healthy.sum() > 50:
        yellow = (h >= 18) & (h < 32) & (s >= 70) & (v >= 90)
        out["yellowing_share"] = round(float((yellow & healthy).sum() / max(1, tissue.sum())), 4)
    if lesion.sum() > 20:
        lv, ls, lh = v[lesion].mean(), s[lesion].mean(), np.median(h[lesion])
        if lv < 85:
            tone = "dark"            # dark brown / black: dead tissue
        elif 18 <= lh < 34 and ls > 80:
            tone = "yellow"          # chlorosis
        elif ls < 60:
            tone = "grey"            # grey / tan, dry
        else:
            tone = "brown"
        out["lesion_tone"] = tone
        n, lab, st, _ = cv2.connectedComponentsWithStats(lesion.astype(np.uint8))
        if n > 1:
            areas = st[1:, 4] / max(1, tissue.sum())
            out["mean_area_share"] = round(float(areas.mean()), 4)
            out["largest_area_share"] = round(float(areas.max()), 4)
    return out


def recommend(severity, affected, spots, m, plant=None, weather=None):
    """-> {summary, today[], week[], prevention[], expert, why[]} - short, concrete, cautious."""
    today, week, prev, why = [], [], [], []
    humid = hot = rainy = False
    if weather:
        d0 = weather[0]
        rh = d0.get("rh")
        humid = rh is not None and rh >= 0.7
        hot = (d0.get("tmax_c") or 0) >= 32
        rainy = any((d.get("rain_mm") or 0) >= 2 for d in weather[:3])
        if humid:
            why.append(f"Humid air expected ({rh * 100:.0f} %): fungal leaf diseases spread faster.")
        if rainy:
            why.append("Rain is forecast in the next days: wet leaves help spots spread.")
        if hot:
            why.append(f"Heat expected ({d0.get('tmax_c'):.0f} °C): brown edges can come from water stress, not only disease.")

    tone = m.get("lesion_tone")
    if severity == "none":
        summary = "No damaged area found on this leaf."
        if m.get("yellowing_share", 0) > 0.15:
            summary = "No spots, but part of the leaf is turning yellow."
            today.append("Check the soil: yellowing without spots usually comes from too much or too little water, or hunger.")
            week.append("If the lower leaves yellow first, feed lightly with a balanced liquid fertiliser.")
            why.append(f"About {m['yellowing_share'] * 100:.0f} % of the leaf is yellow.")
        prev.append("Take a photo of the same plant once a week in the same light to catch changes early.")
        return {"summary": summary, "today": today, "week": week, "prevention": prev,
                "expert": None, "why": why, "plant_note": PLANT_NOTES.get(plant, {}).get("check")}

    many_small = spots >= 8 and m.get("mean_area_share", 0) < 0.01
    big_patch = m.get("largest_area_share", 0) >= 0.1

    if many_small:
        summary = "Many small spots: this pattern is typical of a leaf-spot or rust infection."
        why.append(f"{spots} separate small areas were found.")
    elif big_patch:
        summary = "Large damaged patches on the leaf."
        why.append(f"The largest area covers about {m['largest_area_share'] * 100:.0f} % of the leaf.")
    else:
        summary = "A few damaged areas on the leaf."

    if tone == "dark":
        why.append("The damaged tissue is dark: it is dead and will not turn green again.")
    elif tone == "yellow":
        why.append("The marked areas are mostly yellow (chlorosis): this can be nutrition or water stress as well as disease.")
        week.append("Check watering first: soil that stays wet or dries out completely both cause yellow patches.")
    elif tone == "grey":
        why.append("The marked areas are grey or tan and dry.")

    # today: contain
    today.append("Cut off the affected leaves with clean scissors; bin them, do not compost them.")
    today.append("Wipe the scissors with alcohol between plants so you do not carry the problem to other cells.")
    if severity in ("moderate", "high"):
        today.append("Check the neighbouring cells of the same branch today: problems spread along the structure.")
    if severity == "high":
        today.append("Lift this planting pocket out of the structure if you can, to isolate the plant.")

    # this week: change the conditions
    week.append("Water only at the roots, in the morning: INBETWEEN's channels already feed the pocket from below, "
                "so avoid watering over the leaves.")
    if humid or rainy or many_small:
        week.append("Improve airflow: keep the open cells around this plant free and thin out dense growth.")
    if hot and tone in ("brown", "grey", None):
        week.append("In hot spells, check the reservoir of this branch every evening: dry roots make leaf edges brown.")
    week.append("Take a new photo in 3 to 5 days, same light: if the affected share grows, the problem is active.")

    # prevention
    prev.append("Space the planted cells: leaving open cells between plants is part of the INBETWEEN design for airflow.")
    prev.append("Remove fallen leaves from pockets and the drainage tray.")
    if plant in ("cherry_tomato", "chili", "strawberry"):
        prev.append("Do not plant the same family in the same pocket next season (rotate with herbs or lettuce).")

    expert = None
    if severity == "high" or (severity == "moderate" and (humid or rainy)):
        expert = ("Show a sample (photo of both sides of the leaf, and the stem) to a local agronomist or plant nursery "
                  "before using any treatment: the right product depends on the exact disease.")
    elif severity == "moderate":
        expert = "If spots keep spreading after a week of these steps, ask a local agronomist or nursery."

    return {"summary": summary, "today": today, "week": week, "prevention": prev, "expert": expert, "why": why,
            "plant_note": " ".join(x for x in (PLANT_NOTES.get(plant, {}).get("spots"), PLANT_NOTES.get(plant, {}).get("check")) if x)
            or None}
