import sys, networkx as nx, geopandas as gpd, pandas as pd
from shapely.geometry import Point
from shapely.ops import linemerge
D=sys.argv[1]
sec=gpd.read_file(f"{D}/fis_sections.geojson").to_crs(28992)
cls=pd.DataFrame(gpd.read_file(f"{D}/fis_class.geojson").drop(columns="geometry"))
ORDER={"_0":0,"I":1,"II":2,"III":3,"IV":4,"V_A":5,"V_B":6,"VI_A":7,"VI_B":8,"VI_C":9,"VII":10}
def cemt(r):
    m=(r.routekmbegin+r.routekmend)/2
    c=cls[(cls.routeid==r.routeid)&(cls.routekmbegin<=m+1e-6)&(cls.routekmend>=m-1e-6)]
    return c.code.iloc[0] if len(c) else None
sec["cemt"]=sec.apply(cemt,axis=1)
print("sections",len(sec),"with CEMT class:",sec.cemt.notna().sum(), "| classes:", sec.cemt.value_counts().to_dict())
print("columns sample names:", sec.name.head(3).tolist())
def route(min_cls, label):
    ok=sec[sec.cemt.map(lambda c: c is not None and ORDER.get(c,-1)>=min_cls)] if min_cls is not None else sec
    G=nx.Graph()
    for i,r in ok.iterrows():
        a,b,L=r.startjunctionid,r.endjunctionid,r.geometry.length
        if not G.has_edge(a,b) or G[a][b]["length"]>L: G.add_edge(a,b,length=L,row=i)
    for name,lon,lat in (("Volendam",5.0710,52.4950),("Amersfoort",5.3870,52.1610)):
        p=gpd.GeoSeries([Point(lon,lat)],crs=4326).to_crs(28992)[0]
        i=ok.geometry.distance(p).idxmin(); r=ok.loc[i]; line=r.geometry
        line=linemerge(line) if line.geom_type=="MultiLineString" else line
        d=line.project(p)
        G.add_edge(name,r.startjunctionid,length=d,row=i); G.add_edge(name,r.endjunctionid,length=line.length-d,row=i)
        print(f"  [{label}] {name} snapped {p.distance(line):.0f} m onto class {r.cemt}")
    try:
        path=nx.shortest_path(G,"Volendam","Amersfoort",weight="length")
    except nx.NetworkXNoPath:
        print(f"\n[{label}] no path"); return
    km=nx.path_weight(G,path,"length")/1000
    rows=[G[u][w]["row"] for u,w in zip(path,path[1:])]
    cl=[sec.loc[r,"cemt"] for r in rows]; worst=min((c for c in cl if c), key=lambda c:ORDER[c], default=None)
    pts=[]; 
    for r in rows:
        c=sec.loc[r].geometry.centroid; pts.append(c)
    ll=gpd.GeoSeries(pts,crs=28992).to_crs(4326)
    n=len(ll); way=[(round(ll.iloc[min(n-1,k*n//6)].y,3),round(ll.iloc[min(n-1,k*n//6)].x,3)) for k in range(7)]
    print(f"\n[{label}] distance {km:.1f} km | {len(rows)} sections | smallest class on route: {worst}")
    print("  waypoints (lat,lon):", way)
route(None,"all FIS fairways")
route(0,"any CEMT-classed fairway")
route(1,"CEMT I and up (commercial)")
route(4,"CEMT IV and up")
