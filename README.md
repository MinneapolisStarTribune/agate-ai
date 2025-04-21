# Agate

Agate is a service that uses large language models to extract structured data from unstructured news articles, supplying context and other information that are useful in creating products specific to news.

Whereas traditional entity extraction techniques are effective at identifying strings representing people names, places and other named entities, Agate goes a couple steps further. It is able to limit its extraction to places that are editorially relevant; annotates them with additional information (such as addresses, in the case of named places); and it cleans and collapses entities to eliminate redundancy.

The resulting information can be used both to create products that might be useful to readers and journalists (think: mapping restaurant reviews, or crafting hyperlocal newsletters and alerts). And, when placed into a knowledge graph, the extracted entities enable more comprehensive and accurate searching and summarization than traditional retrieval-augmented generation, reducing the risk of hallucination and returning more useful results.

The current version focuses only supports locations, but the same techniques can be applied to other entities, such as people and institutions, or more specific bits of structured information, such as recipes, sports statistics, and other pieces of information often captured in news stories.

Agate is currently in early development, but given early interest from some of our partners we've elected to work in the open. The code here is available under an MIT license.

## Why "Agate?"

[Agate](https://en.wikipedia.org/wiki/Agate_(typography)) is a typographical term that is often used as shorthand to refer to the pages of a newspaper that contain structured and tabular data, such as sports box scores, stock tables and legal notices.

Agate AI turns unstructured data into structured data. The connection seemed to make sense ...

## Running locally

Agate has a lot of dependencies, but we tried to make it simple to run locally for demonstration purposes. Doing so requires subscribing to several external services, most of which have free tiers. Here's how you can quickly bootstrap the service and see it in action.

First, install [Docker](https://www.docker.com/) and docker-compose.

Then do the following:

```
cd conf/env
cp local.minimal.env local.env
```

Next, fill out the following API keys in `conf/env/local.env`:

  - `OPENAI_API_KEY`: LLM calls only support [OpenAI](https://openai.com/) for now.
  - `GEOCODE_EARTH_API_KEY`: API key for [Geocode Earth](https://geocode.earth/) (free tier available). Alternatively, you could run your own local [Pelias](https://github.com/pelias/pelias?tab=readme-ov-file) instance. This is the primary service that geocodes places.

Finally, `cd bin` and `./run-local.sh`.

Agate will expose different endpoints for different types of entity extraction. Each endpoint currently accepts a public URL to a Star Tribune article, via the `?url=` GET parameter. Ultimately it will accept URLs from other news websites, as well as raw text.

Once the service is running, make a request like [this](http://127.0.0.1:5004/locations?url=https://www.startribune.com/easter-morning-fight-on-interstate-minneapolis/601335244) and the output should show up in your Docker logs.

## Adding a new news organization

Agate is designed to work for any publisher, including small ones with limited technical resources. Following from the assumption that not all publishers can provide API endpoints or raw data dumps of their articles, the service (for now) prioritizes using public URLs as inputs.

Until we are able to support using a service like [Jina](https://jina.ai/) or [Firecrawl](https://www.firecrawl.dev/) to handle generic HTML processing from abitrary websites, supporting a new news organization requires writing a custom scraper to extract article text and headlines from each website's unique layout.

The code for this is in `utils/scrape.py` and `utils/scrapers/`. We can help you get up and running if the logic is unclear.

## Deployment

A full-service Agate deployment requires enabling more external services — notably Microsoft Azure.

This work is funded in part by a [grant from the Lenfest Institute](https://www.niemanlab.org/2024/10/the-lenfest-institute-launches-10-million-ai-news-program-for-big-city-dailies-with-backing-from-openai-and-microsoft/), with support from Microsoft and OpenAI. As a result, we've prioritized that platform over AWS and other options for now.

The best advice we can offer on deployment is: If you want to do it, reach out to us and we'll help. We've scripted in the infrastructure in `terraform/` and `bin/azure-provision.sh` and the deployment process in `bin/azure-deploy-web.sh` and `bin/azure-deploy-worker.sh` but it still takes some lifting to get everything working properly.

The short version is: Set the proper API keys and environment variables in `conf/env/local.env` for running locally and `conf/env/azure.env` for deployment to Azure. Sample files with all required keys are included. Set the keys, run `bin/azure-provision.sh` and then, if that works, use the provided deploy scripts. Again, we can help if you need it.

That said, you can enable further capabilies of Agate — even locally — by supplying credentials to some additional services. This is a good next step after the initial bootstrapping. Those services are:

  - `AZURE_NER_ENDPOINT`: Optional endpoint for an [Azure Cognitive Services named-entity recognition endpoint](https://learn.microsoft.com/en-us/azure/ai-services/language-service/named-entity-recognition/overview). This can enrich the list of candidates for the initial location extraction and helps ensure nothing gets missed.

  - `SCRAPER_API_KEY`: Optional key for [ScraperAPI](https://www.scraperapi.com/) proxy service. If your news organization has measures in place to keep you from scraping a URL (like ours does), a service like this can be helpful. Obviously only use this on sites you are authorized to scrape.

  - `GEOCODIO_API_KEY`: [Geocodio](https://www.geocod.io/) is used as a fallback geocoder to handle some special cases where it is simply more effective than geocode.earth. Free/trial tier available.

  - `SLACK_LOG_WEBHOOK_URL`: A URL to a Slack webhook, which can be used to log output and errors in a Slack channel. We sometimes find that more convenient than having to dig through Docker logs. Logic for this is mostly in `utils/slack.py`.

  - `BRAINTRUST_API_KEY`: We don't yet have a comprehensive eval suite set up for this version of Agate, but we do like using [Braintrust](https://braintrust.dev) for evals generally. You can see how that works in `evals/`.

Those variables are all optional but recommended even for running locally.

## Project layout

`/api`: A public Flask API that accepts information extraction requests. Requests kick off asynchronous tasks to process incoming articles.

`/bin`: Scripts to help with running, deploying and provisioning the app.

`/conf`: Various configuration files for local development and deploys

`/evals`: Some early [Braintrust](https://www.braintrust.dev/) evals. Not especially helpful, but they provide a code pattern for creating more.

`/terraform`: Infrastructure definitions

`/tests`: Not actually tests (for now). Just scripts that allow us to run parts of the pipeline one at a tiem for debugging purposes. Needs a lot of work.

`/utils`: Various utilities relied on by the API and worker to perform critical tasks. This includes LLM prompts.

`/worker`: Worker functions that actually perform the information extraction and data processing. They work async using [Celery](https://github.com/celery/celery). Most of the logic is in here.

## Sample input/output

Given an article like [this](https://www.startribune.com/weather-today-winter-storm-minnesota/601231214), Agate will return output like this:

```
{
  "url": "https://www.startribune.com/weather-today-winter-storm-minnesota/601231214",
  "author": "Tim Harlow",
  "pub_date": "2025-03-06T00:44:14.473Z",
  "output_filename": "1d6392b1648edac28191.json",
  "boundaries": {
    "states": [
      {
        "id": "whosonfirst:region:85688727",
        "name": "Minnesota",
        "coordinates": {
          "lat": 46.63636,
          "lng": -94.579641
        },
        "places": [
          "Minnesota",
          "Dennison, MN",
          "Northfield, MN",
          "Elko New Market, MN",
          "Apple Valley, MN",
          "Stillwater, MN",
          "Owatonna, MN",
          "Minneapolis-St. Paul International Airport, MN",
          "Twin Cities, MN",
          "Burnsville, MN",
          "St. Paul, MN",
          "Minneapolis, MN",
          "Robbinsdale, MN",
          "Richfield, MN",
          "Osseo, MN",
          "Plymouth, MN",
          "Coon Rapids, MN",
          "Eden Prairie, MN",
          "Crystal, MN",
          "Golden Valley, MN",
          "West St. Paul, MN",
          "Welch Village, MN"
        ]
      }
    ],
    "counties": [
      {
        "id": "whosonfirst:county:102087843",
        "name": "Goodhue County",
        "coordinates": {
          "lat": 44.408795,
          "lng": -93.030311
        },
        "places": [
          "Dennison, MN",
          "Welch Village, MN"
        ]
      },
      {
        "id": "whosonfirst:county:102087623",
        "name": "Rice County",
        "coordinates": {
          "lat": 44.452922,
          "lng": -93.166592
        },
        "places": [
          "Northfield, MN"
        ]
      },
      {
        "id": "whosonfirst:county:102087041",
        "name": "Scott County",
        "coordinates": {
          "lat": 44.564061,
          "lng": -93.330615
        },
        "places": [
          "Elko New Market, MN"
        ]
      },
      {
        "id": "whosonfirst:county:102087895",
        "name": "Dakota County",
        "coordinates": {
          "lat": 44.746699,
          "lng": -93.20062
        },
        "places": [
          "Apple Valley, MN",
          "Burnsville, MN",
          "West St. Paul, MN"
        ]
      },
      {
        "id": "whosonfirst:county:102087659",
        "name": "Washington County",
        "coordinates": {
          "lat": 45.101759,
          "lng": -92.810322
        },
        "places": [
          "Stillwater, MN"
        ]
      },
      {
        "id": "whosonfirst:county:102087661",
        "name": "Steele County",
        "coordinates": {
          "lat": 44.084041,
          "lng": -93.221816
        },
        "places": [
          "Owatonna, MN"
        ]
      },
      {
        "id": "whosonfirst:county:102087709",
        "name": "Hennepin County",
        "coordinates": {
          "lat": 44.88351,
          "lng": -93.211374
        },
        "places": [
          "Minneapolis-St. Paul International Airport, MN",
          "Twin Cities, MN",
          "Minneapolis, MN",
          "Robbinsdale, MN",
          "Richfield, MN",
          "Osseo, MN",
          "Plymouth, MN",
          "Eden Prairie, MN",
          "Crystal, MN",
          "Golden Valley, MN"
        ]
      },
      {
        "id": "whosonfirst:county:102087007",
        "name": "Ramsey County",
        "coordinates": {
          "lat": 44.95304,
          "lng": -93.09013
        },
        "places": [
          "St. Paul, MN"
        ]
      },
      {
        "id": "whosonfirst:county:102087861",
        "name": "Anoka County",
        "coordinates": {
          "lat": 45.178209,
          "lng": -93.308426
        },
        "places": [
          "Coon Rapids, MN"
        ]
      }
    ],
    "cities": [
      {
        "id": "whosonfirst:locality:85952887",
        "name": "Dennison",
        "coordinates": {
          "lat": 44.408795,
          "lng": -93.030311
        },
        "places": [
          "Dennison, MN"
        ]
      },
      {
        "id": "whosonfirst:locality:85968737",
        "name": "Northfield",
        "coordinates": {
          "lat": 44.452922,
          "lng": -93.166592
        },
        "places": [
          "Northfield, MN"
        ]
      },
      {
        "id": "whosonfirst:locality:85952527",
        "name": "Elko New Market",
        "coordinates": {
          "lat": 44.564061,
          "lng": -93.330615
        },
        "places": [
          "Elko New Market, MN"
        ]
      },
      {
        "id": "whosonfirst:locality:85968509",
        "name": "Apple Valley",
        "coordinates": {
          "lat": 44.746699,
          "lng": -93.20062
        },
        "places": [
          "Apple Valley, MN"
        ]
      },
      {
        "id": "whosonfirst:locality:1729454989",
        "name": "Stillwater",
        "coordinates": {
          "lat": 45.101759,
          "lng": -92.810322
        },
        "places": [
          "Stillwater, MN"
        ]
      },
      {
        "id": "whosonfirst:locality:85968951",
        "name": "Owatonna",
        "coordinates": {
          "lat": 44.084041,
          "lng": -93.221816
        },
        "places": [
          "Owatonna, MN"
        ]
      },
      {
        "id": "whosonfirst:locality:85953191",
        "name": "St. Paul",
        "coordinates": {
          "lat": 44.88351,
          "lng": -93.211374
        },
        "places": [
          "Minneapolis-St. Paul International Airport, MN",
          "St. Paul, MN"
        ]
      },
      {
        "id": "whosonfirst:locality:85969169",
        "name": "Minneapolis",
        "coordinates": {
          "lat": 44.96313,
          "lng": -93.266563
        },
        "places": [
          "Twin Cities, MN",
          "Minneapolis, MN"
        ]
      },
      {
        "id": "whosonfirst:locality:85968497",
        "name": "Burnsville",
        "coordinates": {
          "lat": 44.759561,
          "lng": -93.285912
        },
        "places": [
          "Burnsville, MN"
        ]
      },
      {
        "id": "whosonfirst:locality:85969129",
        "name": "Robbinsdale",
        "coordinates": {
          "lat": 45.030386,
          "lng": -93.331266
        },
        "places": [
          "Robbinsdale, MN"
        ]
      },
      {
        "id": "whosonfirst:locality:85969131",
        "name": "Richfield",
        "coordinates": {
          "lat": 44.876033,
          "lng": -93.283292
        },
        "places": [
          "Richfield, MN"
        ]
      },
      {
        "id": "whosonfirst:locality:85969141",
        "name": "Osseo",
        "coordinates": {
          "lat": 45.117196,
          "lng": -93.396961
        },
        "places": [
          "Osseo, MN"
        ]
      },
      {
        "id": "whosonfirst:locality:85969137",
        "name": "Plymouth",
        "coordinates": {
          "lat": 45.022139,
          "lng": -93.467323
        },
        "places": [
          "Plymouth, MN"
        ]
      },
      {
        "id": "whosonfirst:locality:85953401",
        "name": "Coon Rapids",
        "coordinates": {
          "lat": 45.178209,
          "lng": -93.308426
        },
        "places": [
          "Coon Rapids, MN"
        ]
      },
      {
        "id": "whosonfirst:locality:85969211",
        "name": "Eden Prairie",
        "coordinates": {
          "lat": 44.849122,
          "lng": -93.462802
        },
        "places": [
          "Eden Prairie, MN"
        ]
      },
      {
        "id": "whosonfirst:locality:85969217",
        "name": "Crystal",
        "coordinates": {
          "lat": 45.051768,
          "lng": -93.355352
        },
        "places": [
          "Crystal, MN"
        ]
      },
      {
        "id": "whosonfirst:locality:85969205",
        "name": "Golden Valley",
        "coordinates": {
          "lat": 44.989143,
          "lng": -93.359894
        },
        "places": [
          "Golden Valley, MN"
        ]
      },
      {
        "id": "whosonfirst:locality:85968433",
        "name": "West St. Paul",
        "coordinates": {
          "lat": 44.901642,
          "lng": -93.085767
        },
        "places": [
          "West St. Paul, MN"
        ]
      },
      {
        "id": "whosonfirst:locality:1729461181",
        "name": "Welch",
        "coordinates": {
          "lat": 44.60028,
          "lng": -92.709105
        },
        "places": [
          "Welch Village, MN"
        ]
      }
    ],
    "neighborhoods": [],
    "regions": [
      {
        "id": "5",
        "name": "Southeast Minnesota",
        "coordinates": {
          "lat": 44.408795,
          "lng": -93.030311
        },
        "places": [
          "Dennison, MN",
          "Welch Village, MN"
        ]
      },
      {
        "id": "7",
        "name": "Greater Minnesota",
        "coordinates": {
          "lat": 44.408795,
          "lng": -93.030311
        },
        "places": [
          "Dennison, MN",
          "Welch Village, MN"
        ]
      },
      {
        "id": "1",
        "name": "Twin Cities Metro",
        "coordinates": {
          "lat": 44.564061,
          "lng": -93.330615
        },
        "places": [
          "Elko New Market, MN"
        ]
      }
    ]
  },
  "places": [
    {
      "original_text": "Gov. Tim Walz declared a peacetime emergency Wednesday and authorized the Minnesota National Guard to provide support for emergency storm operations.",
      "location": "Minnesota",
      "type": "state",
      "importance": "primary",
      "description": "The state where the peacetime emergency was declared due to the storm.",
      "geocode": {
        "geocode": "structured",
        "region": "Minnesota",
        "results": {
          "id": "85688727",
          "label": "Minnesota, USA",
          "geometry": {
            "type": "Point",
            "coordinates": [
              -94.579641,
              46.63636
            ]
          },
          "confidence": {
            "score": 1,
            "match_type": "exact",
            "accuracy": "centroid"
          },
          "boundaries": {
            "neighborhood": {
              "id": null,
              "name": null
            },
            "city": {
              "id": null,
              "name": null
            },
            "county": {
              "id": null,
              "name": null
            },
            "state": {
              "id": "whosonfirst:region:85688727",
              "name": "Minnesota"
            }
          }
        }
      }
    },
    {
      "original_text": "The storm dropped 13 inches of snow in Dennison, about an hour southeast of the Twin Cities, with 11 inches or more reported in Northfield, Elko New Market, Apple Valley, Stillwater and Owatonna, the National Weather Service said.",
      "location": "Dennison, MN",
      "type": "city",
      "importance": "primary",
      "description": "Dennison received 13 inches of snow, one of the highest amounts reported.",
      "geocode": {
        "geocode": "search",
        "text": "Dennison, MN",
        "results": {
          "id": "85952887",
          "label": "Dennison, MN, USA",
          "geometry": {
            "type": "Point",
            "coordinates": [
              -93.030311,
              44.408795
            ]
          },
          "confidence": {
            "score": 1,
            "match_type": "exact",
            "accuracy": "centroid"
          },
          "boundaries": {
            "neighborhood": {
              "id": null,
              "name": null
            },
            "city": {
              "id": "whosonfirst:locality:85952887",
              "name": "Dennison"
            },
            "county": {
              "id": "whosonfirst:county:102087843",
              "name": "Goodhue County"
            },
            "state": {
              "id": "whosonfirst:region:85688727",
              "name": "Minnesota"
            }
          }
        }
      }
    },
    {
      "original_text": "The storm dropped 13 inches of snow in Dennison, about an hour southeast of the Twin Cities, with 11 inches or more reported in Northfield, Elko New Market, Apple Valley, Stillwater and Owatonna, the National Weather Service said.",
      "location": "Northfield, MN",
      "type": "city",
      "importance": "primary",
      "description": "Northfield reported 11 inches or more of snow from the storm.",
      "geocode": {
        "geocode": "search",
        "text": "Northfield, MN",
        "results": {
          "id": "85968737",
          "label": "Northfield, MN, USA",
          "geometry": {
            "type": "Point",
            "coordinates": [
              -93.166592,
              44.452922
            ]
          },
          "confidence": {
            "score": 1,
            "match_type": "exact",
            "accuracy": "centroid"
          },
          "boundaries": {
            "neighborhood": {
              "id": null,
              "name": null
            },
            "city": {
              "id": "whosonfirst:locality:85968737",
              "name": "Northfield"
            },
            "county": {
              "id": "whosonfirst:county:102087623",
              "name": "Rice County"
            },
            "state": {
              "id": "whosonfirst:region:85688727",
              "name": "Minnesota"
            }
          }
        }
      }
    },
    {
      "original_text": "The storm dropped 13 inches of snow in Dennison, about an hour southeast of the Twin Cities, with 11 inches or more reported in Northfield, Elko New Market, Apple Valley, Stillwater and Owatonna, the National Weather Service said.",
      "location": "Elko New Market, MN",
      "type": "city",
      "importance": "primary",
      "description": "Elko New Market reported 11 inches or more of snow from the storm.",
      "geocode": {
        "geocode": "search",
        "text": "Elko New Market, MN",
        "results": {
          "id": "85952527",
          "label": "Elko New Market, MN, USA",
          "geometry": {
            "type": "Point",
            "coordinates": [
              -93.330615,
              44.564061
            ]
          },
          "confidence": {
            "score": 1,
            "match_type": "exact",
            "accuracy": "centroid"
          },
          "boundaries": {
            "neighborhood": {
              "id": null,
              "name": null
            },
            "city": {
              "id": "whosonfirst:locality:85952527",
              "name": "Elko New Market"
            },
            "county": {
              "id": "whosonfirst:county:102087041",
              "name": "Scott County"
            },
            "state": {
              "id": "whosonfirst:region:85688727",
              "name": "Minnesota"
            }
          }
        }
      }
    },
    {
      "original_text": "The storm dropped 13 inches of snow in Dennison, about an hour southeast of the Twin Cities, with 11 inches or more reported in Northfield, Elko New Market, Apple Valley, Stillwater and Owatonna, the National Weather Service said.",
      "location": "Apple Valley, MN",
      "type": "city",
      "importance": "primary",
      "description": "Apple Valley reported 11 inches or more of snow from the storm.",
      "geocode": {
        "geocode": "search",
        "text": "Apple Valley, MN",
        "results": {
          "id": "85968509",
          "label": "Apple Valley, MN, USA",
          "geometry": {
            "type": "Point",
            "coordinates": [
              -93.20062,
              44.746699
            ]
          },
          "confidence": {
            "score": 1,
            "match_type": "exact",
            "accuracy": "centroid"
          },
          "boundaries": {
            "neighborhood": {
              "id": null,
              "name": null
            },
            "city": {
              "id": "whosonfirst:locality:85968509",
              "name": "Apple Valley"
            },
            "county": {
              "id": "whosonfirst:county:102087895",
              "name": "Dakota County"
            },
            "state": {
              "id": "whosonfirst:region:85688727",
              "name": "Minnesota"
            }
          }
        }
      }
    },
    {
      "original_text": "The storm dropped 13 inches of snow in Dennison, about an hour southeast of the Twin Cities, with 11 inches or more reported in Northfield, Elko New Market, Apple Valley, Stillwater and Owatonna, the National Weather Service said.",
      "location": "Stillwater, MN",
      "type": "city",
      "importance": "primary",
      "description": "Stillwater reported 11 inches or more of snow from the storm.",
      "geocode": {
        "geocode": "search",
        "text": "Stillwater, MN",
        "results": {
          "id": "1729454989",
          "label": "Stillwater, MN, USA",
          "geometry": {
            "type": "Point",
            "coordinates": [
              -92.810322,
              45.101759
            ]
          },
          "confidence": {
            "score": 1,
            "match_type": "exact",
            "accuracy": "centroid"
          },
          "boundaries": {
            "neighborhood": {
              "id": null,
              "name": null
            },
            "city": {
              "id": "whosonfirst:locality:1729454989",
              "name": "Stillwater"
            },
            "county": {
              "id": "whosonfirst:county:102087659",
              "name": "Washington County"
            },
            "state": {
              "id": "whosonfirst:region:85688727",
              "name": "Minnesota"
            }
          }
        }
      }
    },
    {
      "original_text": "The storm dropped 13 inches of snow in Dennison, about an hour southeast of the Twin Cities, with 11 inches or more reported in Northfield, Elko New Market, Apple Valley, Stillwater and Owatonna, the National Weather Service said.",
      "location": "Owatonna, MN",
      "type": "city",
      "importance": "primary",
      "description": "Owatonna reported 11 inches or more of snow from the storm.",
      "geocode": {
        "geocode": "search",
        "text": "Owatonna, MN",
        "results": {
          "id": "85968951",
          "label": "Owatonna, MN, USA",
          "geometry": {
            "type": "Point",
            "coordinates": [
              -93.221816,
              44.084041
            ]
          },
          "confidence": {
            "score": 1,
            "match_type": "exact",
            "accuracy": "centroid"
          },
          "boundaries": {
            "neighborhood": {
              "id": null,
              "name": null
            },
            "city": {
              "id": "whosonfirst:locality:85968951",
              "name": "Owatonna"
            },
            "county": {
              "id": "whosonfirst:county:102087661",
              "name": "Steele County"
            },
            "state": {
              "id": "whosonfirst:region:85688727",
              "name": "Minnesota"
            }
          }
        }
      }
    },
    {
      "original_text": "The official yardstick for the metro area at the Minneapolis-St. Paul International Airport measured 9.5 inches as of midday Wednesday, the Weather Service said.",
      "location": "Minneapolis-St. Paul International Airport, MN",
      "type": "place",
      "importance": "primary",
      "description": "The airport is the official measurement site for the metro area, recording 9.5 inches of snow.",
      "geocode": {
        "geocode": "search",
        "text": "4300 Glumack Dr, St Paul, MN 55111, United States",
        "results": {
          "id": "us/mn/hennepin-addresses-county:6eab9859d8a8e8d2",
          "label": "4300 Glumack Drive, St. Paul, MN, USA",
          "geometry": {
            "type": "Point",
            "coordinates": [
              -93.211374,
              44.88351
            ]
          },
          "confidence": {
            "score": 1,
            "match_type": "exact",
            "accuracy": "point"
          },
          "boundaries": {
            "neighborhood": {
              "id": null,
              "name": null
            },
            "city": {
              "id": "whosonfirst:locality:85953191",
              "name": "St. Paul"
            },
            "county": {
              "id": "whosonfirst:county:102087709",
              "name": "Hennepin County"
            },
            "state": {
              "id": "whosonfirst:region:85688727",
              "name": "Minnesota"
            }
          }
        }
      }
    },
    {
      "original_text": "That was the most of the season in the Twin Cities, which previously had been 5.5 inches on Dec. 19.",
      "location": "Twin Cities, MN",
      "type": "region_city",
      "importance": "primary",
      "description": "The Twin Cities experienced the season's largest snowfall, impacting daily life.",
      "geocode": {
        "geocode": "none",
        "text": "Twin Cities, MN",
        "results": {
          "id": "85969169",
          "label": "Minneapolis, MN, USA",
          "geometry": {
            "type": "Point",
            "coordinates": [
              -93.266563,
              44.96313
            ]
          },
          "confidence": {
            "score": 1,
            "match_type": "exact",
            "accuracy": "centroid"
          },
          "boundaries": {
            "neighborhood": {
              "id": null,
              "name": null
            },
            "city": {
              "id": "whosonfirst:locality:85969169",
              "name": "Minneapolis"
            },
            "county": {
              "id": "whosonfirst:county:102087709",
              "name": "Hennepin County"
            },
            "state": {
              "id": "whosonfirst:region:85688727",
              "name": "Minnesota"
            }
          }
        }
      }
    },
    {
      "original_text": "\u201cI love this,\u201d said Nam Bang O, as he plowed out of his driveway in Burnsville on Wednesday morning.",
      "location": "Burnsville, MN",
      "type": "city",
      "importance": "secondary",
      "description": "Burnsville is where a resident expressed enjoyment of the snow.",
      "geocode": {
        "geocode": "search",
        "text": "Burnsville, MN",
        "results": {
          "id": "85968497",
          "label": "Burnsville, MN, USA",
          "geometry": {
            "type": "Point",
            "coordinates": [
              -93.285912,
              44.759561
            ]
          },
          "confidence": {
            "score": 1,
            "match_type": "exact",
            "accuracy": "centroid"
          },
          "boundaries": {
            "neighborhood": {
              "id": null,
              "name": null
            },
            "city": {
              "id": "whosonfirst:locality:85968497",
              "name": "Burnsville"
            },
            "county": {
              "id": "whosonfirst:county:102087895",
              "name": "Dakota County"
            },
            "state": {
              "id": "whosonfirst:region:85688727",
              "name": "Minnesota"
            }
          }
        }
      }
    },
    {
      "original_text": "Treacherous conditions led St. Paul Public Schools to call an e-learning day.",
      "location": "St. Paul, MN",
      "type": "city",
      "importance": "primary",
      "description": "St. Paul Public Schools switched to e-learning due to the storm.",
      "geocode": {
        "geocode": "search",
        "text": "St. Paul, MN",
        "results": {
          "id": "85953191",
          "label": "St. Paul, MN, USA",
          "geometry": {
            "type": "Point",
            "coordinates": [
              -93.09013,
              44.95304
            ]
          },
          "confidence": {
            "score": 1,
            "match_type": "exact",
            "accuracy": "centroid"
          },
          "boundaries": {
            "neighborhood": {
              "id": null,
              "name": null
            },
            "city": {
              "id": "whosonfirst:locality:85953191",
              "name": "St. Paul"
            },
            "county": {
              "id": "whosonfirst:county:102087007",
              "name": "Ramsey County"
            },
            "state": {
              "id": "whosonfirst:region:85688727",
              "name": "Minnesota"
            }
          }
        }
      }
    },
    {
      "original_text": "In Minneapolis, students in kindergarten through fifth grade got the day off for a \u201csevere weather day.\u201d",
      "location": "Minneapolis, MN",
      "type": "city",
      "importance": "primary",
      "description": "Minneapolis schools closed for younger students due to severe weather.",
      "geocode": {
        "geocode": "search",
        "text": "Minneapolis, MN",
        "results": {
          "id": "85969169",
          "label": "Minneapolis, MN, USA",
          "geometry": {
            "type": "Point",
            "coordinates": [
              -93.266563,
              44.96313
            ]
          },
          "confidence": {
            "score": 1,
            "match_type": "exact",
            "accuracy": "centroid"
          },
          "boundaries": {
            "neighborhood": {
              "id": null,
              "name": null
            },
            "city": {
              "id": "whosonfirst:locality:85969169",
              "name": "Minneapolis"
            },
            "county": {
              "id": "whosonfirst:county:102087709",
              "name": "Hennepin County"
            },
            "state": {
              "id": "whosonfirst:region:85688727",
              "name": "Minnesota"
            }
          }
        }
      }
    },
    {
      "original_text": "Several other cities including Robbinsdale, Richfield, Osseo, Plymouth, Coon Rapids, Eden Prairie, Crystal, Golden Valley and West St. Paul also called snow emergencies.",
      "location": "Robbinsdale, MN",
      "type": "city",
      "importance": "primary",
      "description": "Robbinsdale declared a snow emergency due to the storm.",
      "geocode": {
        "geocode": "search",
        "text": "Robbinsdale, MN",
        "results": {
          "id": "85969129",
          "label": "Robbinsdale, MN, USA",
          "geometry": {
            "type": "Point",
            "coordinates": [
              -93.331266,
              45.030386
            ]
          },
          "confidence": {
            "score": 1,
            "match_type": "exact",
            "accuracy": "centroid"
          },
          "boundaries": {
            "neighborhood": {
              "id": null,
              "name": null
            },
            "city": {
              "id": "whosonfirst:locality:85969129",
              "name": "Robbinsdale"
            },
            "county": {
              "id": "whosonfirst:county:102087709",
              "name": "Hennepin County"
            },
            "state": {
              "id": "whosonfirst:region:85688727",
              "name": "Minnesota"
            }
          }
        }
      }
    },
    {
      "original_text": "Several other cities including Robbinsdale, Richfield, Osseo, Plymouth, Coon Rapids, Eden Prairie, Crystal, Golden Valley and West St. Paul also called snow emergencies.",
      "location": "Richfield, MN",
      "type": "city",
      "importance": "primary",
      "description": "Richfield declared a snow emergency due to the storm.",
      "geocode": {
        "geocode": "search",
        "text": "Richfield, MN",
        "results": {
          "id": "85969131",
          "label": "Richfield, MN, USA",
          "geometry": {
            "type": "Point",
            "coordinates": [
              -93.283292,
              44.876033
            ]
          },
          "confidence": {
            "score": 1,
            "match_type": "exact",
            "accuracy": "centroid"
          },
          "boundaries": {
            "neighborhood": {
              "id": null,
              "name": null
            },
            "city": {
              "id": "whosonfirst:locality:85969131",
              "name": "Richfield"
            },
            "county": {
              "id": "whosonfirst:county:102087709",
              "name": "Hennepin County"
            },
            "state": {
              "id": "whosonfirst:region:85688727",
              "name": "Minnesota"
            }
          }
        }
      }
    },
    {
      "original_text": "Several other cities including Robbinsdale, Richfield, Osseo, Plymouth, Coon Rapids, Eden Prairie, Crystal, Golden Valley and West St. Paul also called snow emergencies.",
      "location": "Osseo, MN",
      "type": "city",
      "importance": "primary",
      "description": "Osseo declared a snow emergency due to the storm.",
      "geocode": {
        "geocode": "search",
        "text": "Osseo, MN",
        "results": {
          "id": "85969141",
          "label": "Osseo, MN, USA",
          "geometry": {
            "type": "Point",
            "coordinates": [
              -93.396961,
              45.117196
            ]
          },
          "confidence": {
            "score": 1,
            "match_type": "exact",
            "accuracy": "centroid"
          },
          "boundaries": {
            "neighborhood": {
              "id": null,
              "name": null
            },
            "city": {
              "id": "whosonfirst:locality:85969141",
              "name": "Osseo"
            },
            "county": {
              "id": "whosonfirst:county:102087709",
              "name": "Hennepin County"
            },
            "state": {
              "id": "whosonfirst:region:85688727",
              "name": "Minnesota"
            }
          }
        }
      }
    },
    {
      "original_text": "Several other cities including Robbinsdale, Richfield, Osseo, Plymouth, Coon Rapids, Eden Prairie, Crystal, Golden Valley and West St. Paul also called snow emergencies.",
      "location": "Plymouth, MN",
      "type": "city",
      "importance": "primary",
      "description": "Plymouth declared a snow emergency due to the storm.",
      "geocode": {
        "geocode": "search",
        "text": "Plymouth, MN",
        "results": {
          "id": "85969137",
          "label": "Plymouth, MN, USA",
          "geometry": {
            "type": "Point",
            "coordinates": [
              -93.467323,
              45.022139
            ]
          },
          "confidence": {
            "score": 1,
            "match_type": "exact",
            "accuracy": "centroid"
          },
          "boundaries": {
            "neighborhood": {
              "id": null,
              "name": null
            },
            "city": {
              "id": "whosonfirst:locality:85969137",
              "name": "Plymouth"
            },
            "county": {
              "id": "whosonfirst:county:102087709",
              "name": "Hennepin County"
            },
            "state": {
              "id": "whosonfirst:region:85688727",
              "name": "Minnesota"
            }
          }
        }
      }
    },
    {
      "original_text": "Several other cities including Robbinsdale, Richfield, Osseo, Plymouth, Coon Rapids, Eden Prairie, Crystal, Golden Valley and West St. Paul also called snow emergencies.",
      "location": "Coon Rapids, MN",
      "type": "city",
      "importance": "primary",
      "description": "Coon Rapids declared a snow emergency due to the storm.",
      "geocode": {
        "geocode": "search",
        "text": "Coon Rapids, MN",
        "results": {
          "id": "85953401",
          "label": "Coon Rapids, MN, USA",
          "geometry": {
            "type": "Point",
            "coordinates": [
              -93.308426,
              45.178209
            ]
          },
          "confidence": {
            "score": 1,
            "match_type": "exact",
            "accuracy": "centroid"
          },
          "boundaries": {
            "neighborhood": {
              "id": null,
              "name": null
            },
            "city": {
              "id": "whosonfirst:locality:85953401",
              "name": "Coon Rapids"
            },
            "county": {
              "id": "whosonfirst:county:102087861",
              "name": "Anoka County"
            },
            "state": {
              "id": "whosonfirst:region:85688727",
              "name": "Minnesota"
            }
          }
        }
      }
    },
    {
      "original_text": "Several other cities including Robbinsdale, Richfield, Osseo, Plymouth, Coon Rapids, Eden Prairie, Crystal, Golden Valley and West St. Paul also called snow emergencies.",
      "location": "Eden Prairie, MN",
      "type": "city",
      "importance": "primary",
      "description": "Eden Prairie declared a snow emergency due to the storm.",
      "geocode": {
        "geocode": "search",
        "text": "Eden Prairie, MN",
        "results": {
          "id": "85969211",
          "label": "Eden Prairie, MN, USA",
          "geometry": {
            "type": "Point",
            "coordinates": [
              -93.462802,
              44.849122
            ]
          },
          "confidence": {
            "score": 1,
            "match_type": "exact",
            "accuracy": "centroid"
          },
          "boundaries": {
            "neighborhood": {
              "id": null,
              "name": null
            },
            "city": {
              "id": "whosonfirst:locality:85969211",
              "name": "Eden Prairie"
            },
            "county": {
              "id": "whosonfirst:county:102087709",
              "name": "Hennepin County"
            },
            "state": {
              "id": "whosonfirst:region:85688727",
              "name": "Minnesota"
            }
          }
        }
      }
    },
    {
      "original_text": "Several other cities including Robbinsdale, Richfield, Osseo, Plymouth, Coon Rapids, Eden Prairie, Crystal, Golden Valley and West St. Paul also called snow emergencies.",
      "location": "Crystal, MN",
      "type": "city",
      "importance": "primary",
      "description": "Crystal declared a snow emergency due to the storm.",
      "geocode": {
        "geocode": "search",
        "text": "Crystal, MN",
        "results": {
          "id": "85969217",
          "label": "Crystal, MN, USA",
          "geometry": {
            "type": "Point",
            "coordinates": [
              -93.355352,
              45.051768
            ]
          },
          "confidence": {
            "score": 1,
            "match_type": "exact",
            "accuracy": "centroid"
          },
          "boundaries": {
            "neighborhood": {
              "id": null,
              "name": null
            },
            "city": {
              "id": "whosonfirst:locality:85969217",
              "name": "Crystal"
            },
            "county": {
              "id": "whosonfirst:county:102087709",
              "name": "Hennepin County"
            },
            "state": {
              "id": "whosonfirst:region:85688727",
              "name": "Minnesota"
            }
          }
        }
      }
    },
    {
      "original_text": "Several other cities including Robbinsdale, Richfield, Osseo, Plymouth, Coon Rapids, Eden Prairie, Crystal, Golden Valley and West St. Paul also called snow emergencies.",
      "location": "Golden Valley, MN",
      "type": "city",
      "importance": "primary",
      "description": "Golden Valley declared a snow emergency due to the storm.",
      "geocode": {
        "geocode": "search",
        "text": "Golden Valley, MN",
        "results": {
          "id": "85969205",
          "label": "Golden Valley, MN, USA",
          "geometry": {
            "type": "Point",
            "coordinates": [
              -93.359894,
              44.989143
            ]
          },
          "confidence": {
            "score": 1,
            "match_type": "exact",
            "accuracy": "centroid"
          },
          "boundaries": {
            "neighborhood": {
              "id": null,
              "name": null
            },
            "city": {
              "id": "whosonfirst:locality:85969205",
              "name": "Golden Valley"
            },
            "county": {
              "id": "whosonfirst:county:102087709",
              "name": "Hennepin County"
            },
            "state": {
              "id": "whosonfirst:region:85688727",
              "name": "Minnesota"
            }
          }
        }
      }
    },
    {
      "original_text": "Several other cities including Robbinsdale, Richfield, Osseo, Plymouth, Coon Rapids, Eden Prairie, Crystal, Golden Valley and West St. Paul also called snow emergencies.",
      "location": "West St. Paul, MN",
      "type": "city",
      "importance": "primary",
      "description": "West St. Paul declared a snow emergency due to the storm.",
      "geocode": {
        "geocode": "search",
        "text": "West St. Paul, MN",
        "results": {
          "id": "85968433",
          "label": "West St. Paul, MN, USA",
          "geometry": {
            "type": "Point",
            "coordinates": [
              -93.085767,
              44.901642
            ]
          },
          "confidence": {
            "score": 1,
            "match_type": "exact",
            "accuracy": "centroid"
          },
          "boundaries": {
            "neighborhood": {
              "id": null,
              "name": null
            },
            "city": {
              "id": "whosonfirst:locality:85968433",
              "name": "West St. Paul"
            },
            "county": {
              "id": "whosonfirst:county:102087895",
              "name": "Dakota County"
            },
            "state": {
              "id": "whosonfirst:region:85688727",
              "name": "Minnesota"
            }
          }
        }
      }
    },
    {
      "original_text": "In a bit of irony, even with the all the snow, Welch Village ski area was closed on Wednesday due to a power outage.",
      "location": "Welch Village, MN",
      "type": "place",
      "importance": "primary",
      "description": "Welch Village ski area was closed due to a power outage caused by the storm.",
      "geocode": {
        "geocode": "search",
        "text": "26685 County Road 7 Blvd, Welch, MN 55089",
        "results": {
          "id": "1729461181",
          "label": "Welch, MN, USA",
          "geometry": {
            "type": "Point",
            "coordinates": [
              -92.709105,
              44.60028
            ]
          },
          "confidence": {
            "score": 0.6,
            "match_type": "fallback",
            "accuracy": "centroid"
          },
          "boundaries": {
            "neighborhood": {
              "id": null,
              "name": null
            },
            "city": {
              "id": "whosonfirst:locality:1729461181",
              "name": "Welch"
            },
            "county": {
              "id": "whosonfirst:county:102087843",
              "name": "Goodhue County"
            },
            "state": {
              "id": "whosonfirst:region:85688727",
              "name": "Minnesota"
            }
          }
        }
      }
    }
  ]
}
```

## Questions?

Ask Chase: chase.davis@startribune.com