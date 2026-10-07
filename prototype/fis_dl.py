import json, requests, sys
B="https://geo.rijkswaterstaat.nl/arcgis/rest/services/GDR/fis_vnds/MapServer"
env="4.90,52.05,5.65,52.60"
def get(layer):
    feats=[]; off=0
    while True:
        r=requests.get(f"{B}/{layer}/query",params=dict(where="1=1",outFields="*",geometry=env,geometryType="esriGeometryEnvelope",inSR=4326,outSR=4326,spatialRel="esriSpatialRelIntersects",f="geojson",resultOffset=off,resultRecordCount=1000),timeout=120)
        r.raise_for_status(); d=r.json(); f=d.get("features",[]); feats+=f; off+=len(f)
        if not f or not d.get("exceededTransferLimit") and len(f)<1000: break
    return {"type":"FeatureCollection","features":feats}
for L,n in ((58,"fis_sections"),(49,"fis_class")):
    fc=get(L); json.dump(fc,open(f"{sys.argv[1]}/{n}.geojson","w")); print(n,len(fc["features"]))
