# Agate

Agate is a service that uses large language models to extract structured data from unstructured news articles, supplying context and other information that are useful in creating products specific to news.

Whereas traditional entity extraction techniques are effective at identifying strings representing people names, places and other named entities, Agate goes a couple steps further. It supplies context about the entity and its relevance to the story — for example, noting that an address is where a crime took place. And it cleans and collapses entities to eliminate redundancy. The same techniques being used here can also extract data from articles that traditional entity extraction models might not be trained to identify, such as recipes and box scores.

The resulting information can be used both to create products that might be useful to readers and journalists (think: mapping restaurant reviews, or crafting hyperlocal newsletters and alerts). And, when placed into a knowledge graph, the extracted entities enable more comprehensive and accurate searching and summarization than traditional retrieval-augmented generation, reducing the risk of hallucination and returning more useful results.

This tool is in VERY early development. It's mostly just a fancy prototype at this point. But it works well enough to be promising ...

## Endpoints

Agate exposes endpoints for different types of entity extraction. Each endpoint currently accepts a public URL to a Star Tribune article, via the `?url=` GET parameter. Ultimately it will accept URLs from other news websites, as well as raw text.

**/locations:**: Extracts and characterizes location information from the article and places the result in an Azure storage container.

Endpoints coming soon will include `/people`, `/organizations`, `/events`, `/quotes` and other, more specific cases.

## Project layout

`/api`: A public Flask API that accepts information extraction requests. Requests kick off asynchronous tasks to process incoming articles.

`/bin`: Scripts to help with running, deploying and provisioning the app.

`/conf`: Various configuration files for local development and deploys

`/evals`: Some early [Braintrust](https://www.braintrust.dev/) evals. They work, but don't trust them yet.

`/terraform`: Infrastructure definitions

`/utils`: Various utilities relied on by the API and worker to perform critical tasks. This includes LLM prompts.

`/worker`: Worker functions that actually perform the information extraction and data processing. They work async using [Celery](https://github.com/celery/celery).

## Local development

At minimum, the Agate prototype requires a subscription to Azure and an Azure storage bucket. This will change soon to allow pure local development using the filesystem. It also requires API keys for OpenAI, Google Maps and ScraperAPI. Again, these will eventually be optional (except probably OpenAI).

To run the application locally, first apply the proper environment variables to `conf/env/local.env` (you can use `local.sample.env` as a starting point). Then make sure you have `docker-compose` installed and run:

```
cd bin
./run-local.sh
```

The application should be available at [http://127.0.0.1:5004](http://127.0.0.1:5004).

## Deployment

Agate is currently set up for deployment on Microsoft Azure infrastructure, using Terraform. The Terraform definitions are in `terraform/azure/prd`. The provisioning process is outlined in `./bin/azure-provision.sh`. Until things are cleaned up a bit, YMMV.

## Sample input/output

Given an article like [this](https://www.startribune.com/weather-today-winter-storm-minnesota/601231214), Agate will return output like this:

```
{
  "story_type": {
    "headline": "Winter storm wallops metro, southern Minnesota with rain, snow and wind",
    "category": "weather",
    "rationale": "The headline describes a weather event, specifically a winter storm affecting a region with rain, snow, and wind.",
    "confidence": 1.0
  },
  "text": "Schools are closed or delayed, snow emergencies are in effect and travel is downright difficult after a winter storm battered the metro area and much of southern Minnesota overnight.\n\nIn the Twin Cities, Metro Transit and Maple Grove Transit have suspended bus service until further notice, the agencies said. Light-rail trains continued to operate.\n\nA few more inches of heavy wet snow will fall Wednesday in the metro area morning before a winter storm warning ends at 3 p.m., the National Weather Service said.\n\nBlizzard warnings remained in effect across southern Minnesota as winds gusting to 45 mph was blowing snow around reducing visibility and creating whiteout conditions, the weather service said.\n\nA number of major roads remained closed Wednesday morning, including Interstate 90 between Luverne and Blue Earth. A no-travel advisory was in effect for Freeborn, Faribault, Blue Earth, Brown, Waseca, Nicollet, Le Sueur, Rock and Sibley counties, the Minnesota Department of Transportation said.\n\nAt 6:30 a.m., metro area roads remained snow covered and littered with crashes and spin outs, according to MnDOT.\n\n\u201cEvery incident slows things down,\u201d said MnDOT spokeswoman Anne Meyer, reiterating the need to drive slow and leave plenty of room between vehicles.\n\nPlows hit the roads Tuesday night and will be on the job all day Wednesday, Meyer said. Wet slushy snow and wind blowing it around will hamper efforts until weather conditions improve, she said.\n\n\u201cIt will be a long day,\u201d Meyer said. \u201cIt was quite a storm.\u201d\n\nTreacherous conditions led St. Paul Public Schools to call an e-learning day. In Minneapolis, students in kindergarten through grade 5 get the day off due to a \u201cSevere Weather Day.\u201d Students in grades six to 12 will have an e-learning day, the district said.\n\nCentennial, Bloomington, Lakeville, Wayzata, Osseo and Mounds View are among suburban districts switching to a flexible or at home learning day while others such Robbinsdale and Anoka-Hennepin closed for the day.\n\nNeither Minneapolis nor St. Paul had called a snow emergency as of 5:30 a.m., but other cities such as Robbinsdale, Eden Prairie, Crystal, Golden Valley have.\n\nMetro Mobility warned riders that trips could be delayed Wednesday and asked customers who could reschedule their trips to do so.\n\nMinnesota Valley Transit Authority said its on-demand ride service, Connect, would not operate until 8 a.m. due to ice and snow.\n\nAbout 8,000 Xcel Energy customers were without power Wednesday morning, the utility said.\n\nSnow totals were still coming, but the leader appeared to be Woodbury, where 10 inches of snow had fallen as of early Wednesday.\n\nOther totals included:",
  "headline": "Winter storm wallops metro, southern Minnesota with rain, snow and wind",
  "locations": [
    {
      "original_text": "metro area",
      "location": "Twin Cities, MN",
      "type": "primary",
      "nature": "affected_by",
      "description": "The winter storm battered this area",
      "formatted_address": "Twin Cities, MN, USA",
      "lat": 44.9374831,
      "lng": -93.20099979999999,
      "place_id": "ChIJj1O3W_0p9ocRIKSuqIbBcNA",
      "types": [
        "colloquial_area",
        "political"
      ]
    },
    {
      "original_text": "Interstate 90 between Luverne and Blue Earth",
      "location": "Luverne, MN",
      "type": "primary",
      "nature": "affected_by",
      "description": "Major road closed due to the storm",
      "formatted_address": "Luverne, MN 56156, USA",
      "lat": 43.6555249,
      "lng": -96.2025289,
      "place_id": "ChIJE2SnO6P3i4cR1I5-WctBoPc",
      "types": [
        "locality",
        "political"
      ]
    },
    {
      "original_text": "Interstate 90 between Luverne and Blue Earth",
      "location": "Blue Earth, MN",
      "type": "primary",
      "nature": "affected_by",
      "description": "Major road closed due to the storm",
      "formatted_address": "Blue Earth, MN 56013, USA",
      "lat": 43.6375818,
      "lng": -94.10239059999999,
      "place_id": "ChIJdZgTTZ8S9IcRHm_YMSIdTy0",
      "types": [
        "locality",
        "political"
      ]
    },
    {
      "original_text": "Freeborn, Faribault, Blue Earth, Brown, Waseca, Nicollet, Le Sueur, Rock and Sibley counties",
      "location": "Freeborn County, MN",
      "type": "primary",
      "nature": "affected_by",
      "description": "No-travel advisory in effect",
      "formatted_address": "Freeborn County, MN, USA",
      "lat": 43.6656285,
      "lng": -93.33889169999999,
      "place_id": "ChIJJauksfcz8YcRuQQWHlxvv1Q",
      "types": [
        "administrative_area_level_2",
        "political"
      ]
    },
    {
      "original_text": "Freeborn, Faribault, Blue Earth, Brown, Waseca, Nicollet, Le Sueur, Rock and Sibley counties",
      "location": "Faribault County, MN",
      "type": "primary",
      "nature": "affected_by",
      "description": "No-travel advisory in effect",
      "formatted_address": "Faribault County, MN, USA",
      "lat": 43.6448766,
      "lng": -93.9878427,
      "place_id": "ChIJyRfkC9kI9IcRx9r4iRqX61o",
      "types": [
        "administrative_area_level_2",
        "political"
      ]
    },
    {
      "original_text": "Freeborn, Faribault, Blue Earth, Brown, Waseca, Nicollet, Le Sueur, Rock and Sibley counties",
      "location": "Blue Earth County, MN",
      "type": "primary",
      "nature": "affected_by",
      "description": "No-travel advisory in effect",
      "formatted_address": "Blue Earth County, MN, USA",
      "lat": 43.9505132,
      "lng": -93.9878427,
      "place_id": "ChIJZ0INuV4V9IcRqEVB10xeEqw",
      "types": [
        "administrative_area_level_2",
        "political"
      ]
    },
    {
      "original_text": "Freeborn, Faribault, Blue Earth, Brown, Waseca, Nicollet, Le Sueur, Rock and Sibley counties",
      "location": "Brown County, MN",
      "type": "primary",
      "nature": "affected_by",
      "description": "No-travel advisory in effect",
      "formatted_address": "Brown County, MN, USA",
      "lat": 44.2294379,
      "lng": -94.645035,
      "place_id": "ChIJ5b9XZBw-9YcRL5bVrsrmvmQ",
      "types": [
        "administrative_area_level_2",
        "political"
      ]
    },
    {
      "original_text": "Freeborn, Faribault, Blue Earth, Brown, Waseca, Nicollet, Le Sueur, Rock and Sibley counties",
      "location": "Waseca County, MN",
      "type": "primary",
      "nature": "affected_by",
      "description": "No-travel advisory in effect",
      "formatted_address": "Waseca County, MN, USA",
      "lat": 43.961388,
      "lng": -93.66232389999999,
      "place_id": "ChIJmzdsy_yi9ocRkG1GfEdBpjo",
      "types": [
        "administrative_area_level_2",
        "political"
      ]
    },
    {
      "original_text": "Freeborn, Faribault, Blue Earth, Brown, Waseca, Nicollet, Le Sueur, Rock and Sibley counties",
      "location": "Nicollet County, MN",
      "type": "primary",
      "nature": "affected_by",
      "description": "No-travel advisory in effect",
      "formatted_address": "Nicollet County, MN, USA",
      "lat": 44.3572855,
      "lng": -94.27436279999999,
      "place_id": "ChIJH7Caf-NT9IcRPniHkZM03VM",
      "types": [
        "administrative_area_level_2",
        "political"
      ]
    },
    {
      "original_text": "Freeborn, Faribault, Blue Earth, Brown, Waseca, Nicollet, Le Sueur, Rock and Sibley counties",
      "location": "Le Sueur County, MN",
      "type": "primary",
      "nature": "affected_by",
      "description": "No-travel advisory in effect",
      "formatted_address": "Le Sueur County, MN, USA",
      "lat": 44.4162493,
      "lng": -93.66232389999999,
      "place_id": "ChIJpSIy1CyH9ocRckAuQtqlMGk",
      "types": [
        "administrative_area_level_2",
        "political"
      ]
    },
    {
      "original_text": "Freeborn, Faribault, Blue Earth, Brown, Waseca, Nicollet, Le Sueur, Rock and Sibley counties",
      "location": "Rock County, MN",
      "type": "primary",
      "nature": "affected_by",
      "description": "No-travel advisory in effect",
      "formatted_address": "Rock County, MN, USA",
      "lat": 43.6927003,
      "lng": -96.3226072,
      "place_id": "ChIJDx4MTFH3i4cRFxtQqT6sBnU",
      "types": [
        "administrative_area_level_2",
        "political"
      ]
    },
    {
      "original_text": "Freeborn, Faribault, Blue Earth, Brown, Waseca, Nicollet, Le Sueur, Rock and Sibley counties",
      "location": "Sibley County, MN",
      "type": "primary",
      "nature": "affected_by",
      "description": "No-travel advisory in effect",
      "formatted_address": "Sibley County, MN, USA",
      "lat": 44.5502089,
      "lng": -94.15137639999999,
      "place_id": "ChIJ5ygCaLm89YcRAXiG_kWmPkI",
      "types": [
        "administrative_area_level_2",
        "political"
      ]
    },
    {
      "original_text": "St. Paul",
      "location": "St. Paul, MN",
      "type": "primary",
      "nature": "affected_by",
      "description": "Public schools called an e-learning day due to the storm",
      "formatted_address": "St Paul, MN, USA",
      "lat": 44.9537029,
      "lng": -93.0899578,
      "place_id": "ChIJnzfp5M7UslIRKS7aP9KRcsg",
      "types": [
        "locality",
        "political"
      ]
    },
    {
      "original_text": "Minneapolis",
      "location": "Minneapolis, MN",
      "type": "primary",
      "nature": "affected_by",
      "description": "Severe Weather Day for students due to the storm",
      "formatted_address": "Minneapolis, MN, USA",
      "lat": 44.977753,
      "lng": -93.2650108,
      "place_id": "ChIJvbt3k5Azs1IRB-56L4TJn5M",
      "types": [
        "locality",
        "political"
      ]
    },
    {
      "original_text": "Centennial, Bloomington, Lakeville, Wayzata, Osseo and Mounds View",
      "location": "Centennial, MN",
      "type": "primary",
      "nature": "affected_by",
      "description": "Schools switching to a flexible or at home learning day",
      "formatted_address": "Circle Pines, MN 55014, USA",
      "lat": 45.1485771,
      "lng": -93.15161239999999,
      "place_id": "ChIJAelaqa4ns1IRlZhS5kqhQio",
      "types": [
        "locality",
        "political"
      ]
    },
    {
      "original_text": "Centennial, Bloomington, Lakeville, Wayzata, Osseo and Mounds View",
      "location": "Bloomington, MN",
      "type": "primary",
      "nature": "affected_by",
      "description": "Schools switching to a flexible or at home learning day",
      "formatted_address": "Bloomington, MN, USA",
      "lat": 44.840798,
      "lng": -93.2982799,
      "place_id": "ChIJh5n0Cfok9ocRvAU53EyXcjo",
      "types": [
        "locality",
        "political"
      ]
    },
    {
      "original_text": "Centennial, Bloomington, Lakeville, Wayzata, Osseo and Mounds View",
      "location": "Lakeville, MN",
      "type": "primary",
      "nature": "affected_by",
      "description": "Schools switching to a flexible or at home learning day",
      "formatted_address": "Lakeville, MN, USA",
      "lat": 44.6496868,
      "lng": -93.24271999999999,
      "place_id": "ChIJRwFh8L839ocR9EvbS0JUfqI",
      "types": [
        "locality",
        "political"
      ]
    },
    {
      "original_text": "Centennial, Bloomington, Lakeville, Wayzata, Osseo and Mounds View",
      "location": "Wayzata, MN",
      "type": "primary",
      "nature": "affected_by",
      "description": "Schools switching to a flexible or at home learning day",
      "formatted_address": "Wayzata, MN, USA",
      "lat": 44.97413,
      "lng": -93.5066217,
      "place_id": "ChIJgaCLo5BMs1IRfPaaRQyuZZ8",
      "types": [
        "locality",
        "political"
      ]
    },
    {
      "original_text": "Centennial, Bloomington, Lakeville, Wayzata, Osseo and Mounds View",
      "location": "Osseo, MN",
      "type": "primary",
      "nature": "affected_by",
      "description": "Schools switching to a flexible or at home learning day",
      "formatted_address": "Osseo, MN 55369, USA",
      "lat": 45.1194091,
      "lng": -93.4024532,
      "place_id": "ChIJye9wFjY4s1IRTzBC9mTrBss",
      "types": [
        "locality",
        "political"
      ]
    },
    {
      "original_text": "Centennial, Bloomington, Lakeville, Wayzata, Osseo and Mounds View",
      "location": "Mounds View, MN",
      "type": "primary",
      "nature": "affected_by",
      "description": "Schools switching to a flexible or at home learning day",
      "formatted_address": "Mounds View, MN 55112, USA",
      "lat": 45.1049656,
      "lng": -93.2085582,
      "place_id": "ChIJPbqoNfYls1IRY9bKyPkPt74",
      "types": [
        "locality",
        "political"
      ]
    },
    {
      "original_text": "Robbinsdale and Anoka-Hennepin",
      "location": "Robbinsdale, MN",
      "type": "primary",
      "nature": "affected_by",
      "description": "Schools closed for the day due to the storm",
      "formatted_address": "Robbinsdale, MN, USA",
      "lat": 45.032187,
      "lng": -93.3385614,
      "place_id": "ChIJOalFpVgxs1IRcvbt_RCa9zU",
      "types": [
        "locality",
        "political"
      ]
    },
    {
      "original_text": "Robbinsdale and Anoka-Hennepin",
      "location": "Anoka, MN",
      "type": "primary",
      "nature": "affected_by",
      "description": "Schools closed for the day due to the storm",
      "formatted_address": "Anoka, MN, USA",
      "lat": 45.1977428,
      "lng": -93.3871758,
      "place_id": "ChIJUYZ7YbwXs1IR5vO6i66MjGs",
      "types": [
        "locality",
        "political"
      ]
    },
    {
      "original_text": "Robbinsdale, Eden Prairie, Crystal, Golden Valley",
      "location": "Eden Prairie, MN",
      "type": "primary",
      "nature": "affected_by",
      "description": "Cities called a snow emergency",
      "formatted_address": "Eden Prairie, MN, USA",
      "lat": 44.8546856,
      "lng": -93.47078599999999,
      "place_id": "ChIJhXY-JeIY9ocRr3JuVT5OgVo",
      "types": [
        "locality",
        "political"
      ]
    },
    {
      "original_text": "Robbinsdale, Eden Prairie, Crystal, Golden Valley",
      "location": "Crystal, MN",
      "type": "primary",
      "nature": "affected_by",
      "description": "Cities called a snow emergency",
      "formatted_address": "Crystal, MN, USA",
      "lat": 45.0327425,
      "lng": -93.3602286,
      "place_id": "ChIJ8zA-ZZg2s1IR3TuDP5bpxfA",
      "types": [
        "locality",
        "political"
      ]
    },
    {
      "original_text": "Robbinsdale, Eden Prairie, Crystal, Golden Valley",
      "location": "Golden Valley, MN",
      "type": "primary",
      "nature": "affected_by",
      "description": "Cities called a snow emergency",
      "formatted_address": "Golden Valley, MN, USA",
      "lat": 44.9917149,
      "lng": -93.3600034,
      "place_id": "ChIJacxbQmE0s1IROzf646j7wSU",
      "types": [
        "locality",
        "political"
      ]
    },
    {
      "original_text": "Woodbury",
      "location": "Woodbury, MN",
      "type": "primary",
      "nature": "affected_by",
      "description": "Received 10 inches of snow",
      "formatted_address": "Woodbury, MN, USA",
      "lat": 44.9238552,
      "lng": -92.9593797,
      "place_id": "ChIJq5WdlOnZ94cREIwdp_0Er4s",
      "types": [
        "locality",
        "political"
      ]
    }
  ],
  "cross_check": {
    "check": "ok"
  }
}
```

## Questions?

Ask Chase: chase.davis@startribune.com